"""Evaluate deterministic retrieval in a fresh process: python -m evaluation.offline --help."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from unittest.mock import patch

import hw4


def evaluate(folder: Path) -> dict:
    """Score labeled fixtures. Fail on an attempted connection or retrieval contract violation."""
    with (patch("socket.getaddrinfo", side_effect=RuntimeError("offline evaluation")),
          patch("socket.socket.connect", side_effect=RuntimeError("offline evaluation")),
          patch("socket.socket.connect_ex", side_effect=RuntimeError("offline evaluation"))):
        return score_fixtures(folder)


def score_fixtures(folder: Path) -> dict:
    docs = hw4.load_json(folder / "docs.json")
    tables = hw4.load_json(folder / "tables.json")
    questions = hw4.load_json(folder / "questions.json")
    labels = hw4.load_json(folder / "ground_truth.json")
    corpus = hw4.load_corpus(folder / "corpus")
    if questions.keys() != labels.keys() or corpus.keys() != docs.keys():
        raise ValueError("Incomplete public fixture labels")

    table_scores = [hw4.table_score(hw4.table_to_text(t["html"]), t) for t in tables]
    chunks = []
    locators = {}
    passed = 0
    for source, html in corpus.items():
        group = hw4.chunk_document(source, html)
        passed += not hw4.document_problems(group, None, docs[source], source)
        for ordinal, chunk in enumerate(group):
            if isinstance(chunk, hw4.Document) and len(chunk.page_content) <= hw4.MAX_CHUNK_CHARS:
                locators[id(chunk)] = [source, ordinal]
                chunks.append(chunk)

    parsed = {key: hw4.parse_query(q) for key, q in questions.items()}
    index = hw4.build_index(chunks)
    rows = {}
    categories = {}
    answerable = kept = hits = rejected = 0
    for key, question in questions.items():
        result = hw4.retrieve(index, question)
        if not isinstance(result, list) or len(result) > hw4.MAX_RETRIEVED:
            raise ValueError(f"Invalid retrieval list for {key}")
        if any(id(c) not in locators for c in result):
            raise ValueError(f"Retrieved a chunk outside the original index for {key}")
        gold = labels[key]
        hit = None
        if gold["evidence"]:
            answerable += 1
            kept += bool(result)
            hit = hw4.retrieval_hit(result, gold)
            hits += hit
            counts = categories.setdefault(gold["category"], [0, 0])
            counts[0] += hit
            counts[1] += 1
        else:
            rejected += not result
        rows[key] = {"ranked_chunks": [locators[id(c)] for c in result], "hit": hit,
                     "parse_score": round(hw4.parse_score(parsed[key], gold), 3)}

    # Hash the bytes actually read from disk, including uncommitted fixture edits.
    files = [folder / f for f in ("docs.json", "tables.json", "questions.json", "ground_truth.json")]
    files.extend(folder / "corpus" / source for source in corpus)
    fingerprints = [(str(f.relative_to(folder)), hashlib.sha256(f.read_bytes()).hexdigest())
                    for f in sorted(files)]
    digest = hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest()
    return {"fixtures_sha256": digest, "metrics": {
        "chunks": len(chunks), "longest_chunk": max((len(c.page_content) for c in chunks), default=0),
        "documents_passed": [passed, len(docs)], "table_mean": mean(table_scores),
        "parse_mean": mean(r["parse_score"] for r in rows.values()),
        "valid_nonempty": [kept, answerable], "recall": [hits, answerable],
        "recall_by_category": categories, "rejected": [rejected, len(rows) - answerable],
        "student_usage": hw4.USAGE.summary(),
    }, "questions": rows}


def compare(previous: dict, current: dict) -> dict:
    if previous["fixtures_sha256"] != current["fixtures_sha256"]:
        raise ValueError("Comparison requires identical fixtures")
    before, after = previous["questions"], current["questions"]
    return {
        "metrics_before": previous["metrics"], "metrics_after": current["metrics"],
        "gained_hits": [k for k in after if after[k]["hit"] and not before[k]["hit"]],
        "lost_hits": [k for k in after if before[k]["hit"] and not after[k]["hit"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-folder", type=Path, default=Path("public_test"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path, help="previous offline report on the same fixtures")
    args = parser.parse_args()
    report = evaluate(args.data_folder)
    summary = compare(json.loads(args.compare.read_text()), report) if args.compare else report["metrics"]
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
