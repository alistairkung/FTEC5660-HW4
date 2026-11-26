import unittest
from unittest.mock import patch

import hw4


def report(company, year, text, kind="annual_report"):
    return hw4.Document(page_content=text, metadata={
        "company": company, "fiscal_year": year, "doc_type": kind,
        "source": f"{company}-{year}-{kind}.html",
    })


class EvidenceAbstention(unittest.TestCase):
    def setUp(self):
        self.annual = report("Alder Freight Ltd.", 2030, "Turnover | 2030: 100 | 2029: 95")
        self.peer = report("Alder Logistics", 2030, "Cash | FY2028: 14")
        self.forecast = report("Alder Freight Ltd.", 2030, "Forecast FY2032 revenue is 123.", "research_report")
        self.index = hw4.build_index([self.annual, self.peer, self.forecast])

    def test_explicit_absent_subject_and_similar_existing_company(self):
        absent = ["What was Alder Shipping’s revenue in FY2030?",
                  "How much revenue did Alder Shipping generate in FY2030?"]
        for q in absent:
            with self.subTest(question=q):
                self.assertEqual(hw4.retrieve(self.index, q), [])
        result = hw4.retrieve(self.index, "What was Alder Freight's revenue in FY2030?")
        self.assertEqual({id(chunk) for chunk in result}, {id(self.annual), id(self.forecast)})

    def test_uncertain_entities_keep_global_retrieval(self):
        ambiguous = report("Alder Freight Inc.", 2030, "Revenue")
        index = hw4.build_index([*self.index.chunks, ambiguous])
        for q in ("What was Alder Freight's revenue in FY2030?",
                  "How much did alder logistics earn?",
                  "Which had more cash: Alder Logistics or Absent Company?",
                  "What was Alder Logistics Holdings' revenue in FY2030?"):
            with self.subTest(question=q):
                self.assertTrue(hw4.retrieve(index, q))
        alias = report("Alder Freight Ltd.", 2030, "Formerly known as Blue Isles.")
        self.assertTrue(hw4.retrieve(hw4.build_index([alias]), "What was Blue Isles' turnover in FY2030?"))
        incomplete = hw4.Document(page_content="Unattributed report")
        self.assertTrue(hw4.retrieve(hw4.build_index([self.annual, incomplete]),
                                     "What was Blue Isles' turnover in FY2030?"))

    def test_historical_year_checks_company_text_and_retains_comparatives(self):
        self.assertEqual(hw4.retrieve(self.index, "What was Alder Freight's cash in FY2028?"), [])
        self.assertTrue(hw4.retrieve(self.index, "What was Alder Freight's revenue in FY2029?"))
        historical = report("Alder Freight Ltd.", 2031, "Revenue | FY2025: 87")
        index = hw4.build_index([self.annual, historical])
        self.assertTrue(hw4.retrieve(index, "What was Alder Freight's revenue in FY2025?"))
        self.assertTrue(hw4.retrieve(self.index,
                                     "Using the FY2030 annual report, what was Alder Freight's cash in FY2028?"))

    def test_old_period_in_comparison_and_present_comparison(self):
        self.assertEqual(hw4.retrieve(self.index,
            "Which company held more cash in FY2028: Alder Freight or Alder Logistics?"), [])
        result = hw4.retrieve(self.index,
            "Which company held more cash in FY2029: Alder Freight or Alder Logistics?")
        self.assertEqual({chunk.metadata["company"] for chunk in result},
                         {"Alder Freight Ltd.", "Alder Logistics"})

    def test_forecast_and_metric_uncertainty_keep_original_retrieval(self):
        with patch("hw4.make_llm", side_effect=AssertionError("model call")):
            for q in ("What FY2032 revenue does Indigo Capital forecast for Alder Freight?",
                      "What was Alder Freight's lobbying expense in FY2030?",
                      "What was Alder Freight's sales income in FY2030?"):
                with self.subTest(question=q):
                    retained = hw4.retrieve(self.index, q)
                    self.assertEqual({id(chunk) for chunk in retained},
                                     {id(self.annual), id(self.forecast)})
