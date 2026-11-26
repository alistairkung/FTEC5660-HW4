import unittest

from hw4 import parse_query


class QueryParsing(unittest.TestCase):
    def check(self, question, companies, year=None, kind="annual_report"):
        self.assertEqual(parse_query(question), dict(companies=companies, fiscal_year=year, doc_type=kind))

    def test_subject_from_question_alone(self):
        self.check("What was Slate River Capital's revenue in fiscal year 2030?",
                   ["Slate River Capital"], 2030)
        self.check("Where is Driftwood Markets headquartered?", ["Driftwood Markets"])
        self.check("How much cash did Slate River Capital Ltd. hold at 31 December 2029?",
                   ["Slate River Capital Ltd."], 2029)

    def test_comparison_preserves_overlapping_names_and_legal_suffix(self):
        self.check("At the end of 2028, which held more cash: Alder Group or Alder Group Holdings?",
                   ["Alder Group", "Alder Group Holdings"], 2028)
        self.check("Compare Iron & Pine, Inc. and Ironwood Markets by headcount in FY2031.",
                   ["Iron & Pine, Inc.", "Ironwood Markets"], 2031)
        self.check("Between Cobalt Systems and Cobalt System Services, who employed more people?",
                   ["Cobalt Systems", "Cobalt System Services"])

    def test_intermediaries_and_document_intent(self):
        self.check("What rating does Amber Capital give Cedar Securities?",
                   ["Cedar Securities"], kind="research_report")
        self.check("What is Amber Capital’s target price for Cedar Securities?",
                   ["Cedar Securities"], kind="research_report")
        self.check("Did Ivory & Finch audit the accounts of Cedar Research in FY2031?",
                   ["Cedar Research"], 2031)
        self.check("Were Cedar Research’s accounts audited by Ivory & Finch?",
                   ["Cedar Research"])
        self.check("According to Bright Advisory, where is Bank of Juniper headquartered?",
                   ["Bank of Juniper"])

    def test_document_year_is_distinct_from_requested_year(self):
        self.check("In its FY2031 results review, what FY2032 revenue does Amber Capital forecast for Cedar Research?",
                   ["Cedar Research"], 2032, "research_report")
        self.check("Using the FY2031 annual report, what was Cedar Research’s revenue at the end of 2030?",
                   ["Cedar Research"], 2030)
        self.check("On its earnings call, what did Cedar Research forecast for fiscal year 2033?",
                   ["Cedar Research"], 2033, "earnings_call")
        self.check("What did Cedar Research report in its FY2031 results review?",
                   ["Cedar Research"], 2031, "research_report")

    def test_coordinated_subjects_can_precede_the_comparison(self):
        self.check("Did Fir Services and Fir Services Group announce dividends during 2034?",
                   ["Fir Services", "Fir Services Group"], 2034)
        self.check("Compare Bay Works, Bay Capital and Bay Logistics for FY2032.",
                   ["Bay Works", "Bay Capital", "Bay Logistics"], 2032)

    def test_explicit_dates_and_a_bare_metric_year(self):
        self.check("What was Stillwater Energy's 2034 operating margin?", ["Stillwater Energy"], 2034)
        self.check("How much cash did Stillwater Energy have on December 31, 2032?",
                   ["Stillwater Energy"], 2032)
        self.check("What happened in FY2030?", [], 2030)

    def test_source_wording_and_year_adjacent_to_metric(self):
        self.check("What did Apex & Oak forecast on its earnings-call transcript?",
                   ["Apex & Oak"], kind="earnings_call")
        self.check("What 2032 revenue did Mount Capital predict for West Research?",
                   ["West Research"], 2032, "research_report")
        self.check("Did West Research spend USD 2024 on freight?", ["West Research"])
