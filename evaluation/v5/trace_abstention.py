"""Explain public abstentions and verify all retained rankings against frozen V4."""

import json
from collections import Counter

import hw4
from evaluation.offline import compare


# Manual classification for the public audit only.
PUBLIC_CLASSES = {
    "absent_company": {"q001", "q011", "q034", "q041", "q044"},
    "unsupported_historical_period": {"q005", "q006", "q028", "q032", "q049"},
    "undisclosed_metric": {"q019", "q025", "q033", "q039"},
}


def main() -> None:
    before = hw4.load_json("evaluation/v4/offline.json")
    after = hw4.load_json("evaluation/v5/offline.json")
    questions = hw4.load_json("public_test/questions.json")
    labels = hw4.load_json("public_test/ground_truth.json")
    public_class = {key: kind for kind, keys in PUBLIC_CLASSES.items() for key in keys}
    assert set(public_class) == {key for key, label in labels.items() if not label["evidence"]}
    index = hw4.build_index([chunk for f, html in hw4.load_corpus("public_test/corpus").items()
                             for chunk in hw4.chunk_document(f, html)])
    retained = 0
    false_abstentions = []
    successful_abstentions = []
    unanswerable_counts = Counter()
    rows = {}
    for key, question in questions.items():
        parsed = hw4.parse_query(question)
        _, resolution = hw4.company_candidates(index, parsed["companies"])
        reason = hw4.abstention_reason(index, question, parsed, resolution)
        v4 = before["questions"][key]
        v5 = after["questions"][key]
        assert v5["parse_score"] == v4["parse_score"]
        if reason is None:
            assert v5["ranked_chunks"] == v4["ranked_chunks"]
            retained += 1
        else:
            assert not v5["ranked_chunks"]
            if key in public_class:
                successful_abstentions.append(key)
                unanswerable_counts[public_class[key]] += 1
            else:
                false_abstentions.append(key)
        rows[key] = {"question": question, "parsed": parsed, "resolution": resolution,
                     "public_class": public_class.get(key, "answerable"), "reason": reason}

    kept, answerable = after["metrics"]["valid_nonempty"]
    rejected, unanswerable = after["metrics"]["rejected"]
    print(json.dumps({
        "comparison": compare(before, after),
        "task_3_points": 10 * max(0, kept / answerable + rejected / unanswerable - 1),
        "retained_rankings_identical": retained,
        "successful_abstentions": successful_abstentions,
        "false_abstentions": false_abstentions,
        "rejected_by_class": {kind: [unanswerable_counts[kind], len(keys)]
                              for kind, keys in PUBLIC_CLASSES.items()},
        "questions": rows,
    }, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
