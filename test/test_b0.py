import hashlib
import json
import unittest
from pathlib import Path

import hw4


class BaselineContracts(unittest.TestCase):
    def test_lecturer_suffix_matches_starter(self):
        source = Path(hw4.__file__).read_bytes()
        marker = b"# Provided code below. Do not change it."
        self.assertEqual(source.count(marker), 1)
        suffix = source[source.index(marker):]
        self.assertEqual(hashlib.sha256(suffix).hexdigest(),
                         "5c938c489015a0dec728dbc21cb442a7e60539e7b0bc21544525dc25fea796c2")

    def test_flattened_text_and_overlap(self):
        text = "x" * 1300 + "y" * 200 + "z" * 300
        html = ("<title>Annual Report 2030</title><h1>Example</h1>"
                "<p>Debt</p><span>(1,020.0)</span>" + text)
        chunks = hw4.chunk_document("opaque.html", html)
        flattened = "Annual Report 2030ExampleDebt(1,020.0)" + text
        # The splitter prefers the spaces in the title before splitting the long word.
        self.assertEqual(chunks[0].page_content, "Annual Report")
        word = flattened.removeprefix("Annual Report")
        self.assertEqual([c.page_content for c in chunks[1:]], [word[:1500].strip(), word[1300:]])
        for c in chunks:
            self.assertEqual(c.metadata, dict(source="opaque.html", company="Example",
                                              fiscal_year=2030, doc_type="annual_report"))

    def test_research_and_call_metadata_follow_report_subject_and_year(self):
        cases = [
            ("A Broker | Example (EX) | FY2030 results review", "research_report"),
            ("Example Q4 and Full Year 2030 Earnings Call Transcript", "earnings_call"),
        ]
        for title, kind in cases:
            with self.subTest(kind=kind):
                html = f"<title>{title}</title><h1>Example (EX)</h1><p>March 2031</p>"
                chunk, = hw4.chunk_document("renamed.html", html)
                self.assertEqual(chunk.metadata, dict(source="renamed.html", company="Example",
                                                      fiscal_year=2030, doc_type=kind))

    def test_whitespace_bm25_returns_original_chunks_and_keeps_unknown_queries(self):
        docs = [hw4.Document(page_content=text, metadata={"source": str(i)})
                for i, text in enumerate(["value,", "VALUE", "a", "b", "c", "d", "e"])]
        index = hw4.build_index(docs)
        for query, first in [("Value,", docs[0]), ("  value  ", docs[1])]:
            results = hw4.retrieve(index, query)
            self.assertIs(results[0], first)
            self.assertEqual(len(results), 5)
            self.assertTrue(all(any(c is original for original in docs) for c in results))
        self.assertEqual(len(hw4.retrieve(index, "unseen")), 5)
        self.assertEqual(hw4.retrieve(hw4.build_index([]), "unseen"), [])
        self.assertEqual(hw4.table_to_text("<table></table>"), "")


class PublicEvaluation(unittest.TestCase):
    def test_offline_scorecard(self):
        from evaluation.offline import evaluate

        report = evaluate(Path(hw4.__file__).parent / "public_test")
        metrics = report["metrics"]
        self.assertEqual((metrics["chunks"], metrics["longest_chunk"]), (650, 1499))
        self.assertEqual(metrics["documents_passed"], [40, 40])
        self.assertEqual(metrics["valid_nonempty"], [46, 46])
        self.assertEqual(metrics["table_mean"], 1.0)
        self.assertEqual(metrics["recall"], [46, 46])
        self.assertEqual(metrics["recall_by_category"],
                         {"fact": [12, 12], "table": [22, 22], "comparison": [12, 12]})
        self.assertEqual(metrics["rejected"], [7, 14])
        self.assertEqual(metrics["student_usage"]["llm_calls"], 0)
        self.assertEqual(len(report["questions"]), 60)
        frozen = json.loads((Path(hw4.__file__).parent / "evaluation/v2/offline.json").read_text())
        self.assertEqual(report["fixtures_sha256"], frozen["fixtures_sha256"])
        self.assertEqual(report["questions"].keys(), frozen["questions"].keys())
        for key, row in report["questions"].items():
            with self.subTest(question_id=key):
                self.assertEqual(row["parse_score"], frozen["questions"][key]["parse_score"])

    def test_comparison_pairs_question_outcomes_and_rejects_other_fixtures(self):
        from evaluation.offline import compare

        def sample(digest, flags):
            return {"fixtures_sha256": digest, "metrics": {},
                    "questions": {k: {"hit": v} for k, v in flags.items()}}

        before = sample("a", {"first": True, "second": False})
        after = sample("a", {"first": False, "second": True})
        delta = compare(before, after)
        self.assertEqual(delta["gained_hits"], ["second"])
        self.assertEqual(delta["lost_hits"], ["first"])
        with self.assertRaises(ValueError):
            compare(before, sample("b", {}))
