"""Trace evidence gains, regressions, and comparison coverage for V5 versus V6."""

import json
from collections import Counter

import hw4
from evaluation.offline import compare


def main() -> None:
    before = hw4.load_json("evaluation/v5/offline.json")
    after = hw4.load_json("evaluation/v6/offline.json")
    labels = hw4.load_json("public_test/ground_truth.json")
    queries = hw4.load_json("public_test/questions.json")
    frozen_parses = hw4.load_json("evaluation/v2/parsed.json")
    chunks = {
        (source, ordinal): chunk
        for source, html in hw4.load_corpus("public_test/corpus").items()
        for ordinal, chunk in enumerate(hw4.chunk_document(source, html))
    }
    coverage = Counter()
    rows = {}
    for key, question in queries.items():
        assert hw4.parse_query(question) == frozen_parses[key]["parsed"]
        old = before["questions"][key]
        new = after["questions"][key]
        assert bool(old["ranked_chunks"]) == bool(new["ranked_chunks"])
        assert old["parse_score"] == new["parse_score"]
        variants = {}
        for name, row in (("v5", old), ("v6", new)):
            chosen = [chunks[tuple(location)] for location in row["ranked_chunks"]]
            if labels[key]["category"] == "comparison":
                expected = {hw4.company_key(name) for name in labels[key]["query"]["companies"]}
                present = {hw4.company_key(c.metadata["company"]) for c in chosen}
                coverage[name] += expected.issubset(present)
            evidence_ranks = [
                next((rank for rank, c in enumerate(chosen, 1)
                      if any(c.metadata["source"] == source and hw4.contains(c.page_content, value)
                             for source, value in group)), None)
                for group in labels[key]["evidence"]
            ]
            assert row["hit"] == (all(rank is not None for rank in evidence_ranks)
                                  if evidence_ranks else None)
            variants[name] = {"evidence_ranks": evidence_ranks, "chunks": row["ranked_chunks"]}
        rows[key] = variants
    print(json.dumps({"comparison": compare(before, after),
                      "both_companies_retrieved": coverage,
                      "questions": rows}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
