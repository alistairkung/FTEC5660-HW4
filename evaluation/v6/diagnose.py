"""Replay the V5 candidate ranking for every public evidence miss."""

import json
import re
from collections import Counter

import hw4


def main() -> None:
    questions = hw4.load_json("public_test/questions.json")
    labels = hw4.load_json("public_test/ground_truth.json")
    frozen = hw4.load_json("evaluation/v5/offline.json")
    locations = []
    chunks = []
    for source, html in hw4.load_corpus("public_test/corpus").items():
        for ordinal, chunk in enumerate(hw4.chunk_document(source, html)):
            locations.append([source, ordinal])
            chunks.append(chunk)

    index = hw4.build_index(chunks)
    positions = {tuple(location): pos for pos, location in enumerate(locations)}
    misses = {}
    for key, question in questions.items():
        baseline = frozen["questions"][key]
        if baseline["hit"] is not False:
            continue
        parsed = hw4.parse_query(question)
        eligible, resolution = hw4.company_candidates(index, parsed["companies"])
        ranking = hw4.ranked_positions(index, question)
        ranking = [pos for pos in ranking if eligible is None or pos in eligible]
        returned = [positions[tuple(loc)] for loc in baseline["ranked_chunks"]]
        scores = index.ranker.get_scores(question.lower().split())
        groups = []
        for alternatives in labels[key]["evidence"]:
            matches = {pos: printed
                       for source, printed in alternatives
                       for pos, chunk in enumerate(chunks)
                       if chunk.metadata["source"] == source and hw4.contains(chunk.page_content, printed)}
            first = next(((rank, pos) for rank, pos in enumerate(ranking, 1) if pos in matches), None)
            hit = next((rank for rank, pos in enumerate(returned, 1) if pos in matches), None)
            evidence = None
            if first is not None:
                rank, pos = first
                value = matches[pos]
                line = next((line for line in chunks[pos].page_content.splitlines()
                             if hw4.contains(line, value)), "")
                evidence = {"rank": rank, "location": locations[pos], "score": round(float(scores[pos]), 6),
                            "value": value, "excerpt": line[:300]}
            groups.append({"returned_rank": hit, "eligible_evidence": evidence,
                           "matching_chunks_in_corpus": len(matches)})
        selected = [chunks[pos] for pos in returned]
        preferred_type = parsed["doc_type"]
        wrong_type = sum(chunk.metadata["doc_type"] != preferred_type for chunk in selected)
        missing = [group["eligible_evidence"] for group in groups if group["returned_rank"] is None]
        row_label = {hw4.squash(evidence["excerpt"].split("|", 1)[0]) for evidence in missing
                     if evidence and "|" in evidence["excerpt"]}
        related_rows = [
            {"location": locations[pos], "text": line}
            for pos in returned
            for line in chunks[pos].page_content.splitlines()
            if "|" in line and hw4.squash(line.split("|", 1)[0]) in row_label
        ]
        year = parsed["fiscal_year"]
        wrong_year_rows = [
            row for row in related_rows if year is not None
            and (periods := re.findall(r"(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])", row["text"]))
            and str(year) not in periods
        ]
        misses[key] = {"question": question, "category": labels[key]["category"],
                       "parsed": parsed, "resolution": resolution, "evidence_groups": groups,
                       "returned_other_document_types": wrong_type,
                       "missing_groups_in_rendered_rows": len(row_label) > 0,
                       "related_rows": related_rows, "related_rows_without_requested_year": wrong_year_rows,
                       "returned": [{"location": locations[pos], "metadata": chunks[pos].metadata,
                                     "score": round(float(scores[pos]), 6)} for pos in returned]}
    counts = Counter()
    for row in misses.values():
        groups = [g for g in row["evidence_groups"] if g["returned_rank"] is None]
        counts["eligible_below_top_five"] += any(
            g["eligible_evidence"] and g["eligible_evidence"]["rank"] > 5 for g in groups)
        counts["missing_evidence_in_rendered_rows"] += row["missing_groups_in_rendered_rows"]
        counts["some_other_document_types"] += row["returned_other_document_types"] > 0
        counts["only_other_document_types"] += row["returned_other_document_types"] == len(row["returned"])
        counts["related_numeric_row_absent"] += (
            row["missing_groups_in_rendered_rows"] and not row["related_rows"])
        counts["related_row_without_requested_year"] += bool(row["related_rows_without_requested_year"])
        counts["comparison_incomplete"] += row["category"] == "comparison"
        counts["no_contiguous_evidence_in_corpus"] += any(
            g["matching_chunks_in_corpus"] == 0 for g in groups)
        counts["other_prose_misses"] += not row["missing_groups_in_rendered_rows"]
    print(json.dumps({"counts": counts, "questions": misses},
                     indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
