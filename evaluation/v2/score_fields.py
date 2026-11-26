"""From the repository root: python -m evaluation.v2.score_fields > parsed.json."""

import json
from pathlib import Path

import hw4


def main() -> None:
    folder = Path("public_test")
    questions = hw4.load_json(folder / "questions.json")
    labels = hw4.load_json(folder / "ground_truth.json")
    rows = {}
    for key, question in questions.items():
        parsed = hw4.parse_query(question)
        gold = labels[key]
        # The lecturer gives one third of a point for each correct field,
        # so submitting a single field isolates its contribution.
        fields = {field: hw4.parse_score({field: parsed[field]}, gold) == 1 / 3
                  for field in ("companies", "fiscal_year", "doc_type")}
        rows[key] = {"question": question, "parsed": parsed, "correct_by_field": fields,
                     "score": hw4.parse_score(parsed, gold)}
        if not all(fields.values()):
            rows[key]["expected"] = gold["query"]
    print(json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
