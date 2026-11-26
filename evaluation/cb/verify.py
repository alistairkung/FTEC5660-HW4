"""Replay the frozen C+B public trace and optionally audit a native paid run."""

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from unittest.mock import patch

from bs4 import BeautifulSoup

import hw4
from evaluation.offline import evaluate


HERE = Path(__file__).resolve().parent
PUBLIC = Path("public_test")
MARKER = b"# Provided code below. Do not change it."


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def prompt_digest(question: str, chunks: list[hw4.Document]) -> str | None:
    if not chunks:
        return None
    prompt = hw4.GENERATOR_PROMPT.format(question=question, context=hw4.format_context(chunks))
    return sha(prompt.encode())


def check_files(reference: dict) -> None:
    for name, expected in reference["measured_source_sha256"].items():
        require(sha(Path(name).read_bytes()) == expected, f"Measured file changed: {name}")
    baseline = subprocess.check_output(["git", "show", f'{reference["base_commit"]}:hw4.py'])
    suffix = Path("hw4.py").read_bytes().split(MARKER, 1)[1]
    require(suffix == baseline.split(MARKER, 1)[1], "Protected code differs from V6")
    require(sha(suffix) == reference["protected_suffix_sha256"], "Protected digest changed")
    require(sha(Path("evaluation/b0/requirements.lock").read_bytes()) == reference["dependency_lock_sha256"],
            "Environment lock changed")
    for name, expected in reference["archived_run_sha256"].items():
        require(sha((HERE / "research" / name).read_bytes()) == expected, f"Archived run changed: {name}")


def source_material(source: str, html: str) -> tuple[list, set[str]]:
    """Rebuild the parent text and independently enumerate document-local labeled cells."""
    soup = BeautifulSoup(html, "html.parser")
    metadata = hw4.report_metadata(source, soup)
    allowed_children = set()
    for table in soup.find_all("table"):
        rendered = hw4.table_to_text(str(table))
        caption_tag = table.find("caption")
        if caption_tag:
            caption = caption_tag.get_text(" ", strip=True)
            lines = rendered.splitlines()
            if caption in lines:
                for line in lines[lines.index(caption) + 1:]:
                    label, *fields = line.split(" | ")
                    allowed_children.update(f"{caption}\n{label} | {field}" for field in fields)
        table.replace_with("\n" + rendered + "\n")
    splitter = hw4.RecursiveCharacterTextSplitter(chunk_size=hw4.MAX_CHUNK_CHARS, chunk_overlap=200)
    return splitter.create_documents([soup.get_text()], [metadata]), allowed_children


def verified_index() -> tuple[hw4.LexicalIndex, dict, list[int]]:
    corpus = hw4.load_corpus(PUBLIC / "corpus")
    metadata = hw4.load_json(PUBLIC / "docs.json")
    chunks = []
    locations = {}
    parent_count = child_count = 0
    for source, html in corpus.items():
        produced = hw4.chunk_document(source, html)
        parents, local_cells = source_material(source, html)
        require(not hw4.document_problems(produced, None, metadata[source], source), f"Document failed: {source}")
        ordinary = [c for c in produced if not c.metadata.get(hw4.CELL_CHILD)]
        require([(c.page_content, c.metadata) for c in ordinary] == [(c.page_content, c.metadata) for c in parents],
                f"V6 parents changed: {source}")
        for ordinal, chunk in enumerate(produced):
            require(chunk.metadata["source"] == source and len(chunk.page_content) <= hw4.MAX_CHUNK_CHARS,
                    f"Chunk length or source failed: {source}/{ordinal}")
            if chunk.metadata.get(hw4.CELL_CHILD):
                require(chunk.page_content in local_cells and
                        chunk.metadata == parents[0].metadata | {hw4.CELL_CHILD: True},
                        f"Cell source linkage failed: {source}/{ordinal}")
                child_count += 1
            else:
                parent_count += 1
            locations[id(chunk)] = [source, ordinal]
        chunks.extend(produced)
    return hw4.build_index(chunks), locations, [parent_count, child_count]


def check_runner_prompts(questions: dict, prompts: dict) -> None:
    """Exercise canonicalization in the unmodified runner without calling the generator."""
    qids = {question: key for key, question in questions.items()}
    captured = {}
    lock = Lock()

    def observe(question: str, chunks: list[hw4.Document]) -> str:
        with lock:
            captured[qids[question]] = prompt_digest(question, chunks)
        return "NOT_FOUND"

    with (
        TemporaryDirectory(prefix="hw4-cb-dry-") as temporary,
        patch.object(sys, "argv", ["hw4.py", "--data-folder", str(PUBLIC),
                                  "--output", str(Path(temporary) / "dry.csv")]),
        patch.object(hw4, "generate", observe),
        redirect_stdout(StringIO()),
    ):
        hw4.main()
    require(captured == prompts, "The lecturer runner saw a different prompt")


def replay(reference: dict) -> dict:
    check_files(reference)
    measured = reference["variants"]["combined"]
    scores = evaluate(PUBLIC)
    require(scores["fixtures_sha256"] == reference["public_fixtures_sha256"] and
            scores["metrics"] == measured["metrics"], "Fixture or scorecard differs from the measured run")
    questions = hw4.load_json(PUBLIC / "questions.json")
    index, locations, counts = verified_index()
    prompts = {}
    for key, question in questions.items():
        selected = hw4.retrieve(index, question)
        require(len(selected) <= hw4.MAX_RETRIEVED and all(id(c) in locations for c in selected),
                f"Retrieval did not return original chunks within five slots: {key}")
        row = measured["questions"][key]
        prompts[key] = prompt_digest(question, selected)
        require([locations[id(c)] for c in selected] == row["locations"] and
                prompts[key] == row["prompt_sha256"] and hw4.parse_query(question) == row["parsed"] and
                scores["questions"][key]["hit"] == row["hit"], f"Frozen evidence or prompt differs: {key}")
    check_runner_prompts(questions, prompts)
    return {"questions": len(questions), "byte_identical_prompts": sum(value is not None for value in prompts.values()),
            "empty_inputs": sum(value is None for value in prompts.values()),
            "parent_child_counts": counts, "metrics": scores["metrics"]}


def read_csv(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 60 and len({r["id"] for r in rows}) == 60, f"Invalid lecturer CSV: {path}")
    return {r["id"]: r for r in rows}


def compare_live(reference: dict, directory: Path) -> dict:
    paths = {
        "v6": Path("evaluation/v6/results.csv"), "c": HERE / "research/track-c.csv",
        "b": HERE / "research/track-b.csv", "measured_combined": HERE / "research/combined.csv",
        "fresh_combined": directory / "results.csv",
    }
    runs = {name: read_csv(path) for name, path in paths.items()}
    labels = hw4.load_json(PUBLIC / "ground_truth.json")
    questions = hw4.load_json(PUBLIC / "questions.json")
    categories = {name: defaultdict(lambda: [0, 0]) for name in runs}
    rows = {}
    for key, gold in labels.items():
        outcomes = {}
        for name, records in runs.items():
            row = records[key]
            trace = reference["variants"]["combined" if name.endswith("combined") else name]["questions"][key]
            hit = trace["hit"]
            correct = hw4.answer_correct(row["answer"], gold)
            require(row["question"] == questions[key] and row["category"] == gold["category"] and
                    row["valid"] == "True" and row["parse_score"] == "1.0" and bool(row["answer"]) and
                    json.loads(row["parsed"]) == trace["parsed"] and row["retrieved"] == ";".join(trace["sources"]) and
                    row["retrieval_hit"] == ("" if hit is None else str(hit)) and row["correct"] == str(correct),
                    f"CSV audit failed: {name}/{key}")
            count = categories[name][gold["category"]]
            count[0] += correct
            count[1] += 1
            outcomes[name] = {"answer": row["answer"], "correct": correct, "prompt_sha256": trace["prompt_sha256"]}
        rows[key] = outcomes
    deltas = {}
    for name in runs:
        if name == "fresh_combined":
            continue
        pairs = [(key, outcomes[name], outcomes["fresh_combined"]) for key, outcomes in rows.items()]
        deltas[name] = {
            "gained": [key for key, old, new in pairs if not old["correct"] and new["correct"]],
            "lost": [key for key, old, new in pairs if old["correct"] and not new["correct"]],
            "changed_answers_on_identical_prompts": [key for key, old, new in pairs
                                                     if old["prompt_sha256"] == new["prompt_sha256"]
                                                     and old["answer"] != new["answer"]],
        }
    log = (directory / "runner.txt").read_text(encoding="utf-8")
    require("Generator failed" not in log, "Lecturer logged a generator failure")
    generator = ast.literal_eval(re.search(r"^Generator usage: (.*)$", log, re.M)[1])
    student = ast.literal_eval(re.search(r"^Your usage: (.*)$", log, re.M)[1])
    points = {task: float(value) for task, value in re.findall(r"^  Task ([0-9.]+)\s+([\d.]+) / ", log, re.M)}
    total = float(re.search(r"^  Total\s+([\d.]+) / 75$", log, re.M)[1])
    correct = sum(count[0] for count in categories["fresh_combined"].values())
    require(generator["llm_calls"] == 53 and student["llm_calls"] == 0, "Unexpected model call totals")
    static_points = {"1.1": 8.0, "1.2": 7.0, "2.1": 5.0, "2.2": 10.0, "2.3": 15.0, "3": 5.0}
    accuracy_points = hw4.POINTS["4"] * correct / 60
    require(points == static_points | {"4": round(accuracy_points, 2)} and
            total == round(sum(static_points.values()) + accuracy_points, 2), "Unexpected lecturer points")
    generator["estimated_usd"] = (generator["llm_input_tokens"] * hw4.PRICE_LLM_INPUT +
                                  generator["llm_output_tokens"] * hw4.PRICE_LLM_OUTPUT) / 1_000_000
    return {"points": points, "total": total, "correct": correct, "categories": categories,
            "deltas": deltas, "questions": rows, "generator_usage": generator, "student_usage": student,
            "lecturer_seconds": float(re.search(r"^Time: ([\d.]+)s", log, re.M)[1])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-dir", type=Path, help="audit that directory's results.csv and runner.txt offline")
    args = parser.parse_args()
    reference = json.loads((HERE / "reference.json").read_text(encoding="utf-8"))
    with (
        patch("socket.getaddrinfo", side_effect=AssertionError("offline replay")),
        patch("socket.socket.connect", side_effect=AssertionError("offline replay")),
        patch("socket.socket.connect_ex", side_effect=AssertionError("offline replay")),
    ):
        result = {"replay": replay(reference)}
        if args.live_dir is not None:
            result["live"] = compare_live(reference, args.live_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
