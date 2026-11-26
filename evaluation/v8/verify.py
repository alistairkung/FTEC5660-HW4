"""Verify V8 offline, and audit or execute one explicitly requested native grader run."""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from dotenv import dotenv_values

import hw4
from evaluation.cb.verify import MARKER, check_runner_prompts, prompt_digest, read_csv, require, sha, verified_index
from evaluation.offline import evaluate
from evaluation.v8.assemble import BASELINE, BASELINE_SHA, assembled

HERE = Path(__file__).resolve().parent
PUBLIC = Path("public_test")
PANEL = HERE / "fresh-panel"
BASE_DIR = Path("evaluation/cb")
EXPECTED_REJECTIONS = ["q005", "q028", "q049"]
EXPECTED_SCOPE = {"answerables": 15, "kept": 15, "hits": 14, "unanswerables": 7, "rejected": 3}
DEADLINE_SECONDS = 120


def dump(path: Path, result: dict) -> None:
    with path.open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2, sort_keys=True)
        target.write("\n")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_source(research: Path | None) -> str:
    source = Path(hw4.__file__).read_bytes()
    baseline = subprocess.check_output(["git", "show", f"{BASELINE}:hw4.py"])
    reference = load(BASE_DIR / "reference.json")
    require(sha(baseline) == BASELINE_SHA, "C+B source hash changed")
    suffix = source.split(MARKER, 1)[1]
    require(suffix == baseline.split(MARKER, 1)[1], "Lecturer suffix differs")
    require(sha(suffix) == reference["protected_suffix_sha256"], "Lecturer suffix hash differs")
    require(sha(Path("evaluation/b0/requirements.lock").read_bytes()) == reference["dependency_lock_sha256"],
            "Dependency lock differs")
    require(sha(MARKER + suffix) == load(HERE / "research-freeze.json")["protected_source_sha256"],
            "Research protected hash differs")
    if research:
        require(source == assembled(research).encode(), "Runtime differs from mechanical assembly of frozen sources")
    return sha(source)


def check_public() -> dict:
    reference = load(BASE_DIR / "reference.json")
    measured = reference["variants"]["combined"]
    score = evaluate(PUBLIC)
    require(score["fixtures_sha256"] == reference["public_fixtures_sha256"], "Public fixtures differ")
    require(score["metrics"] == measured["metrics"] | {"rejected": [10, 14]}, "Public offline scorecard differs")
    questions = hw4.load_json(PUBLIC / "questions.json")
    index, locations, counts = verified_index()
    require(counts == [330, 320], "Parent or cell counts differ")
    prompts, rows = {}, {}
    added, lost = [], []
    for key, question in questions.items():
        ranked = hw4.retrieve(index, question)
        require(isinstance(ranked, list) and len(ranked) <= hw4.MAX_RETRIEVED
                and all(id(doc) in locations for doc in ranked), f"Invalid retrieval: {key}")
        prev = measured["questions"][key]
        prompt = prompt_digest(question, ranked)
        slots = [locations[id(doc)] for doc in ranked]
        parsed = hw4.parse_query(question)
        hit = score["questions"][key]["hit"]
        require(parsed == prev["parsed"] and hit == prev["hit"], f"Parsing or evidence changed: {key}")
        require(slots == score["questions"][key]["ranked_chunks"], f"Independent ranking differs: {key}")
        if ranked:
            require(slots == prev["locations"] and prompt == prev["prompt_sha256"],
                    f"Retained rankings or prompt changed: {key}")
        if prev["locations"] and not slots:
            require(hit is None, f"False abstention: {key}")
            added.append(key)
        if slots and not prev["locations"]:
            lost.append(key)
        prompts[key] = prompt
        rows[key] = {"locations": slots, "prompt_sha256": prompt, "parsed": parsed, "evidence_hit": hit,
                     "sources": sorted({doc.metadata["source"] for doc in ranked})}
    require(sorted(added) == EXPECTED_REJECTIONS and not lost, "Unexpected abstention delta")
    check_runner_prompts(questions, prompts)
    return {"metrics": score["metrics"], "parent_child_counts": counts, "questions": rows,
            "identical_retained": sum(p is not None for p in prompts.values()), "false_abstentions": [],
            "gained_abstentions": sorted(added), "lost_abstentions": lost,
            "gained_evidence_hits": [], "lost_evidence_hits": []}


def index_corpus(corpus: dict) -> tuple:
    chunks, locations = [], {}
    for source, html in sorted(corpus.items()):
        for ordinal, chunk in enumerate(hw4.chunk_document(source, html)):
            require(chunk.metadata["source"] == source and len(chunk.page_content) <= hw4.MAX_CHUNK_CHARS,
                    f"Malformed evidence chunk: {source}/{ordinal}")
            chunks.append(chunk)
            locations[id(chunk)] = [source, ordinal]
    return hw4.build_index(chunks), locations


def check_panel() -> dict:
    trace = load(HERE / "approved-panel.json")
    seal = (PANEL / "source.sha256").read_bytes()
    require(sha(seal) == trace["seal_sha256"], "Synthetic panel seal differs")
    for line in seal.decode().splitlines():
        expected, name = line.split(maxsplit=1)
        require(sha((PANEL / name).read_bytes()) == expected, f"Sealed file differs: {name}")
    questions = load(PANEL / "questions.json")
    labels = load(PANEL / "labels.json")
    require(questions.keys() == labels.keys() == trace["questions"].keys(), "Incomplete sealed panel")
    index, locations = index_corpus(hw4.load_corpus(PANEL / "corpus"))
    counts = defaultdict(lambda: dict.fromkeys(EXPECTED_SCOPE, 0))
    rows = {}
    for key, question in questions.items():
        ranked = hw4.retrieve(index, question)
        require(len(ranked) <= hw4.MAX_RETRIEVED and all(id(doc) in locations for doc in ranked),
                f"Invalid sealed retrieval: {key}")
        gold = labels[key]
        parsed = hw4.parse_query(question)
        eligible, resolution = hw4.company_candidates(index, parsed["companies"])
        route = hw4.historical_policy(index, question, parsed, eligible, resolution).route
        hit = hw4.retrieval_hit(ranked, gold) if gold["answerable"] else None
        rows[key] = {"locations": [locations[id(doc)] for doc in ranked], "prompt_sha256": prompt_digest(question, ranked),
                     "evidence_hit": hit, "route": route}
        require(rows[key] == trace["questions"][key], f"Approved sealed trace differs: {key}")
        for cohort in ("all", gold["cohort"]):
            tally = counts[cohort]
            if gold["answerable"]:
                tally["answerables"] += 1
                tally["kept"] += bool(ranked)
                tally["hits"] += hit
            else:
                tally["unanswerables"] += 1
                tally["rejected"] += not ranked
    require(counts["all"] == EXPECTED_SCOPE, "Approved sealed metrics differ")
    return {"cohorts": dict(counts), "questions": rows, "seal_sha256": trace["seal_sha256"]}


def check_research_regressions(research: Path) -> dict:
    heading, veto, v8 = research.parents[:3]
    previous = v8 / "blinded-validation"
    sets = (
        (previous / "panel", previous / "title-compatible-corpus", {"q017": "q017"}),
        (previous / "scope-panel", previous / "scope-panel/corpus",
         {key: key for key in ("s005", "s007", "s010", "s012", "s016")}),
        (veto / "fresh-panel", veto / "fresh-panel/corpus", {"q007": "heading-q007", "q008": "heading-q008"}),
        (heading / "fresh-panel", heading / "fresh-panel/corpus", {"q007": "officer-q007"}),
    )
    approved = load(research / "regressions.json")
    expectations = approved["known_historical_positives"] | {"officer-q007": approved["prior_cfo_case"]}
    observed = {}
    for panel, corpus, keys in sets:
        questions, labels = load(panel / "questions.json"), load(panel / "labels.json")
        index, locations = index_corpus(hw4.load_corpus(corpus))
        for key, name in keys.items():
            ranked = hw4.retrieve(index, questions[key])
            result = {"kept": bool(ranked), "hit": hw4.retrieval_hit(ranked, labels[key])}
            require(result == expectations[name]["v8"], f"Known historical outcome differed: {name}")
            observed[name] = result | {"locations": [locations[id(doc)] for doc in ranked]}
    return observed


def offline(research: Path | None = None) -> tuple[dict, dict | None]:
    with (
        patch("socket.getaddrinfo", side_effect=AssertionError("offline V8 evaluation")),
        patch("socket.socket.connect", side_effect=AssertionError("offline V8 evaluation")),
        patch("socket.socket.connect_ex", side_effect=AssertionError("offline V8 evaluation")),
    ):
        source = check_source(research)
        result = {"source_sha256": source, "public": check_public(), "sealed_panel": check_panel()}
        regressions = check_research_regressions(research) if research else None
        require(hw4.USAGE.llm_calls == 0 and hw4.GENERATOR_USAGE.llm_calls == 0, "Offline model use")
        return result, regressions


def run_native(directory: Path, credential_file: Path | None, trace: dict) -> None:
    credential = os.environ.get("DEEPSEEK_API_KEY")
    if not credential and credential_file:
        credential = dotenv_values(credential_file).get("DEEPSEEK_API_KEY")
    require(bool(credential), "Set the grader credential in the environment or its local credential file")
    directory.mkdir()
    command = [sys.executable, "hw4.py", "--data-folder", str(PUBLIC), "--output", str(directory / "results.csv")]
    launch = perf_counter()
    try:
        result = subprocess.run(command, env=os.environ | {"DEEPSEEK_API_KEY": credential, "PYTHON_DOTENV_DISABLED": "1",
                                                             "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, timeout=DEADLINE_SECONDS)
        log = result.stdout + result.stderr
        execution = {"exit_code": result.returncode, "timed_out": False}
    except subprocess.TimeoutExpired as error:
        log = (error.stdout or b"") + (error.stderr or b"")
        execution = {"exit_code": None, "timed_out": True}
    wall = perf_counter() - launch
    (directory / "runner.txt").write_bytes(log.replace(credential.encode(), b"[REDACTED]"))
    dump(directory / "execution.json", execution | {"process_wall_seconds": wall, "deadline_seconds": DEADLINE_SECONDS,
         "command": ["python", *command[1:]], "source_sha256": trace["source_sha256"]})
    require(execution["exit_code"] == 0, "Native run failed or timed out. See its preserved log and receipt.")


def audit_native(directory: Path, trace: dict) -> dict:
    execution = load(directory / "execution.json")
    require(execution["exit_code"] == 0 and execution["source_sha256"] == trace["source_sha256"],
            "Native execution provenance differs")
    old = read_csv(BASE_DIR / "verification/results.csv")
    current = read_csv(directory / "results.csv")
    questions = hw4.load_json(PUBLIC / "questions.json")
    gold = hw4.load_json(PUBLIC / "ground_truth.json")
    base = load(BASE_DIR / "reference.json")["variants"]["combined"]["questions"]
    rows = {}
    category_score = defaultdict(lambda: [0, 0])
    deltas = {"gained_correct_answers": [], "lost_correct_answers": [], "changed_answers_on_identical_prompts": []}
    for key, evidence in trace["public"]["questions"].items():
        baseline, row, label = old[key], current[key], gold[key]
        correct = hw4.answer_correct(row["answer"], label)
        old_correct = hw4.answer_correct(baseline["answer"], label)
        hit = evidence["evidence_hit"]
        require(row["question"] == questions[key] and row["category"] == label["category"]
                and row["valid"] == "True" and float(row["parse_score"]) == 1.0
                and json.loads(row["parsed"]) == evidence["parsed"] and row["retrieved"] == ";".join(evidence["sources"])
                and row["retrieval_hit"] == ("" if hit is None else str(hit)) and row["correct"] == str(correct),
                f"Native CSV differs from validated trace: {key}")
        counts = category_score[label["category"]]
        counts[0] += correct
        counts[1] += 1
        same_prompt = evidence["prompt_sha256"] is not None and evidence["prompt_sha256"] == base[key]["prompt_sha256"]
        if correct and not old_correct:
            deltas["gained_correct_answers"].append(key)
        if old_correct and not correct:
            deltas["lost_correct_answers"].append(key)
        if same_prompt and baseline["answer"] != row["answer"]:
            deltas["changed_answers_on_identical_prompts"].append(key)
        rows[key] = {"baseline_answer": baseline["answer"], "answer": row["answer"], "expected": label["answer"],
                     "correct": correct, "baseline_correct": old_correct, "same_nonempty_prompt": same_prompt,
                     "evidence_hit": hit, "retained": bool(evidence["locations"])}
    log = (directory / "runner.txt").read_text(encoding="utf-8")
    generator = ast.literal_eval(re.search(r"^Generator usage: (.*)$", log, re.M)[1])
    student = ast.literal_eval(re.search(r"^Your usage: (.*)$", log, re.M)[1])
    points = {task: float(value) for task, value in re.findall(r"^  Task ([0-9.]+)\s+([\d.]+) / ", log, re.M)}
    total = float(re.search(r"^  Total\s+([\d.]+) / 75$", log, re.M)[1])
    correct = sum(row["correct"] for row in rows.values())
    static = {"1.1": 8.0, "1.2": 7.0, "2.1": 5.0, "2.2": 10.0, "2.3": 15.0, "3": 10 * 10 / 14}
    actual = static | {"4": hw4.POINTS["4"] * correct / 60}
    require(points == {key: round(points, 2) for key, points in actual.items()} and total == round(sum(actual.values()), 2),
            "Native points differ from independent score")
    generator["estimated_usd"] = (generator["llm_input_tokens"] * hw4.PRICE_LLM_INPUT
                                  + generator["llm_output_tokens"] * hw4.PRICE_LLM_OUTPUT) / 1_000_000
    return {"total": total, "points": points, "answers_correct": correct, "category_accuracy": dict(category_score),
            "lecturer_seconds": float(re.search(r"^Time: ([\d.]+)s", log, re.M)[1]), "execution": execution,
            "generator_usage": generator, "student_usage": student,
            "generator_failures": re.findall(r"^Generator failed on (q\d+)", log, re.M),
            "questions": rows, "deltas": deltas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path)
    parser.add_argument("--offline-output", type=Path)
    parser.add_argument("--regressions-output", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--run-native", type=Path, metavar="NEW_DIR")
    action.add_argument("--audit-native", type=Path, metavar="RUN_DIR")
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--live-audit-output", type=Path)
    args = parser.parse_args()
    trace, regressions = offline(args.research)
    if args.offline_output:
        dump(args.offline_output, trace)
    if args.regressions_output:
        require(regressions is not None, "--regressions-output requires --research")
        dump(args.regressions_output, regressions)
    summary = {"offline_public": trace["public"]["metrics"], "sealed_panel": trace["sealed_panel"]["cohorts"]}
    if args.run_native:
        run_native(args.run_native, args.credential_file, trace)
    live_dir = args.run_native or args.audit_native
    if live_dir:
        audit = audit_native(live_dir, trace)
        if args.live_audit_output:
            dump(args.live_audit_output, audit)
        summary["live"] = {key: value for key, value in audit.items() if key != "questions"}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
