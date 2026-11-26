"""Record entity resolution and evidence ranks using only the public fixtures."""

import json
from collections import Counter
from pathlib import Path

import hw4
from evaluation.offline import compare


def main() -> None:
    folder = Path("public_test")
    questions = hw4.load_json(folder / "questions.json")
    labels = hw4.load_json(folder / "ground_truth.json")
    before = hw4.load_json("evaluation/v2/offline.json")
    frozen_parses = hw4.load_json("evaluation/v2/parsed.json")
    after = hw4.load_json("evaluation/v3/offline.json")
    locations = []
    chunks = []
    for source, html in hw4.load_corpus(folder / "corpus").items():
        for ordinal, chunk in enumerate(hw4.chunk_document(source, html)):
            locations.append([source, ordinal])
            chunks.append(chunk)

    index = hw4.build_index(chunks)
    rows = {}
    hits_by_subject_count = {}
    resolution = Counter()
    for key, question in questions.items():
        parsed = hw4.parse_query(question)
        assert parsed == frozen_parses[key]["parsed"]
        subjects = parsed["companies"]
        eligible, status = hw4.company_candidates(index, subjects)
        global_ranking = hw4.ranked_positions(index, question)
        candidates = global_ranking if eligible is None else [
            position for position in global_ranking if position in eligible
        ]
        assert [locations[i] for i in global_ranking[:5]] == before["questions"][key]["ranked_chunks"]
        assert [locations[i] for i in candidates[:5]] == after["questions"][key]["ranked_chunks"]
        resolution[status] += 1
        evidence = []
        for group in labels[key]["evidence"]:
            matching = {i for i, chunk in enumerate(chunks)
                        if any(chunk.metadata["source"] == source
                               and hw4.contains(chunk.page_content, printed)
                               for source, printed in group)}
            def best_rank(ranking: list[int]) -> int | None:
                return next((rank for rank, i in enumerate(ranking, 1) if i in matching), None)

            evidence.append({"v2": best_rank(global_ranking), "v3": best_rank(candidates)})
        if evidence:
            group = "multiple" if len(subjects) > 1 else "single" if subjects else "none"
            counts = hits_by_subject_count.setdefault(group, {"v2": 0, "v3": 0, "total": 0})
            counts["v2"] += before["questions"][key]["hit"]
            counts["v3"] += after["questions"][key]["hit"]
            counts["total"] += 1
        rows[key] = {
            "subjects": subjects, "resolution": status, "eligible_chunks": len(candidates),
            "top_five_companies": [chunks[i].metadata["company"] for i in candidates[:5]],
            "evidence_ranks": evidence,
        }
    print(json.dumps({"comparison": compare(before, after), "resolution": resolution,
                      "hits_by_subject_count": hits_by_subject_count, "questions": rows},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
