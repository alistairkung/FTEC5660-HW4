"""Trace public comparison coverage and required evidence ranks for V3 and V4."""

import json
from collections import Counter

import hw4
from evaluation.offline import compare


def evidence_rank(ranking, group, chunks):
    for rank, location in enumerate(ranking, 1):
        chunk = chunks[tuple(location)]
        if any(chunk.metadata["source"] == source and hw4.contains(chunk.page_content, text)
               for source, text in group):
            return rank
    return None


def main() -> None:
    before = hw4.load_json("evaluation/v3/offline.json")
    after = hw4.load_json("evaluation/v4/offline.json")
    reference = hw4.load_json("evaluation/v3/ranks.json")["questions"]
    questions = hw4.load_json("public_test/questions.json")
    labels = hw4.load_json("public_test/ground_truth.json")
    chunks = {
        (source, ordinal): chunk
        for source, html in hw4.load_corpus("public_test/corpus").items()
        for ordinal, chunk in enumerate(hw4.chunk_document(source, html))
    }
    locations = list(chunks)
    index = hw4.build_index(list(chunks.values()))
    coverage = Counter()
    rows = {}
    single_identical = 0
    global_fallback_identical = 0
    for key, question in questions.items():
        v3 = before["questions"][key]
        v4 = after["questions"][key]
        assert v3["parse_score"] == v4["parse_score"]
        subjects = hw4.parse_query(question)["companies"]
        eligible, status = hw4.company_candidates(index, subjects)
        assert subjects == reference[key]["subjects"] and status == reference[key]["resolution"]
        if len(subjects) == 1:
            assert v3["ranked_chunks"] == v4["ranked_chunks"]
            single_identical += 1
        if eligible is None:
            assert v3["ranked_chunks"] == v4["ranked_chunks"]
            global_fallback_identical += 1
        if labels[key]["category"] != "comparison":
            continue
        ranking = [locations[i] for i in hw4.ranked_positions(index, question)
                   if eligible is None or i in eligible]
        assert ranking[:5] == [tuple(location) for location in v3["ranked_chunks"]]

        expected = {hw4.company_key(subject) for subject in labels[key]["query"]["companies"]}
        represented = {
            name: sorted({hw4.company_key(chunks[tuple(location)].metadata["company"])
                          for location in result["ranked_chunks"]})
            for name, result in (("v3", v3), ("v4", v4))
        }
        for name, companies in represented.items():
            coverage[name] += expected.issubset(companies)

        ranks = [{
            "v3_candidate": evidence_rank(ranking, group, chunks),
            "v3_returned": evidence_rank(v3["ranked_chunks"], group, chunks),
            "v4_returned": evidence_rank(v4["ranked_chunks"], group, chunks),
        } for group in labels[key]["evidence"]]
        assert all(row["v4_returned"] is not None for row in ranks) == v4["hit"]
        if v4["hit"]:
            outcome = "complete"
        elif eligible is None:
            outcome = "unresolved_company"
        elif not expected.issubset(represented["v4"]):
            outcome = "missing_company"
        elif any(row["v3_candidate"] is None for row in ranks):
            outcome = "evidence_absent_from_candidate_chunks"
        else:
            outcome = "represented_company_missing_required_evidence"
        rows[key] = {"question": question, "company_coverage": represented, "ranks": ranks,
                     "v3_top_five": v3["ranked_chunks"], "v4_top_five": v4["ranked_chunks"],
                     "outcome": outcome}

    print(json.dumps({
        "comparison": compare(before, after), "coverage": dict(coverage),
        "comparison_questions": len(rows), "single_company_identical": single_identical,
        "global_fallback_identical": global_fallback_identical,
        "outcomes": Counter(r["outcome"] for r in rows.values()), "questions": rows,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
