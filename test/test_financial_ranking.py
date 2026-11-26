import unittest
from unittest.mock import patch

import hw4


def passage(text, company="Prairie Kite Systems", suffix="target"):
    return hw4.Document(page_content=text, metadata={
        "source": suffix + ".html", "company": company, "fiscal_year": 2031,
        "doc_type": "annual_report",
    })


class FinancialRowRanking(unittest.TestCase):
    def test_promotes_unseen_financial_row_from_real_html_above_prose_and_other_rows(self):
        html = """<title>Prairie Kite Systems Annual Report 2031</title>
        <h1>Prairie Kite Systems</h1><table><caption>USD thousands</caption>
        <thead><tr><th>Measure</th><th>2031</th><th>2030</th></tr></thead>
        <tr><td>Unbilled-service receivables</td><td>(1,231.04)</td><td>1,108.30</td></tr>
        </table>"""
        target, = hw4.chunk_document("prairie.html", html)
        distractors = [
            passage("Prairie Kite Systems unbilled service receivables FY2030 accounting policy",
                    suffix="policy"),
            passage("Collected billings | 2030: 3,120.50", suffix="other-metric"),
            passage("Unbilled service receivables | 2030: pending", suffix="no-value"),
            passage("Unbilled service receivables | 2030: 8,225.80",
                    company="Prairie Kite Industrial", suffix="other-company"),
        ]
        index = hw4.build_index([target, *distractors])
        question = "What were Prairie Kite Systems' unbilled service receivables in FY2030?"
        self.assertIs(hw4.retrieve(index, question)[0], target)
        self.assertTrue(all(doc is not distractors[-1] for doc in hw4.retrieve(index, question)))

    def test_ties_preserve_bm25_and_comparison_still_has_each_company(self):
        question = "Which company had higher deferred grants in FY2029: Ember Forge or Azure Fabric?"
        rows = [passage(f"Deferred grants | 2029: {i + 8}.25", "Ember Forge", str(i))
                for i in range(7)]
        rows.append(passage("Deferred grants | 2029: 16.70", "Azure Fabric"))
        index = hw4.build_index(rows)
        before = hw4.ranked_positions(index, question)
        result = hw4.retrieve(index, question)
        self.assertEqual(len(result), 5)
        self.assertIn(rows[-1], result)
        self.assertEqual([id(d) for d in result],
                         [id(rows[i]) for i in before if any(rows[i] is d for d in result)])

    def test_prose_and_nonmatching_row_fall_back_to_existing_order(self):
        docs = [passage("Lab supplies | 2030: 9.50"), passage("Customs duties are disclosed here.")]
        index = hw4.build_index(docs)
        for question in ("What were Prairie Kite Systems' customs duties in FY2030?",
                         "What forecast did Prairie Kite Systems share in its FY2031 earnings call?"):
            baseline = [docs[i] for i in hw4.ranked_positions(index, question)]
            with patch("hw4.make_llm", side_effect=AssertionError("student model call")):
                result = hw4.retrieve(index, question)
            self.assertEqual([id(d) for d in result], [id(d) for d in baseline])

    def test_financial_row_with_grouped_headers_and_unseen_metric(self):
        html = """<title>Prairie Kite Systems Annual Report 2031</title><h1>Prairie Kite Systems</h1>
        <table><caption>Production statistics</caption><thead>
        <tr><th rowspan="2">Measure</th><th colspan="2">Fiscal year</th></tr>
        <tr><th>2031</th><th>2030</th></tr></thead>
        <tbody><tr><th scope="row">Scrap recovery yield</th><td>92.60%</td><td>88.75%</td></tr>
        </tbody></table>"""
        target, = hw4.chunk_document("grouped.html", html)
        prose = passage("Prairie Kite Systems discussed scrap recovery yield in FY2030.")
        index = hw4.build_index([prose, target])
        result = hw4.retrieve(index, "What was Prairie Kite Systems' scrap recovery yield in FY2030?")
        self.assertIs(result[0], target)
        self.assertIn("Fiscal year 2030: 88.75%", result[0].page_content)
