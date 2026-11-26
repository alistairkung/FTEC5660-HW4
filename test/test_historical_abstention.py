import unittest

import hw4


COMPANY = "Larkfield Instruments"


def index_with(note="", governance=""):
    docs = {}
    for year in (2024, 2025):
        docs[f"annual-{year}.html"] = f"""<title>Annual Report {year}</title>
<h1>{COMPANY}</h1>
<h2>Corporate governance</h2>
{governance}
<h2>Financial statements</h2>
<table><caption>Consolidated balance sheet (USD millions)</caption>
<tr><th>Metric</th><th>{year}</th><th>{year - 1}</th></tr>
<tr><th scope="row">Total assets</th><td>829.4</td><td>788.1</td></tr></table>
<h2>Notes to the financial statements</h2>
{note if year == 2024 else ""}
"""
    docs["call.html"] = f"""<title>{COMPANY} Q4 and Full Year 2025 Earnings Call Transcript</title>
<h1>{COMPANY}</h1><p>We invested USD 11 million in FY2025.</p>"""
    docs["broker.html"] = f"""<title>{COMPANY} FY2025 results review</title>
<h1>{COMPANY}</h1><p>FY2026 projected profit is USD 25 million.</p>"""
    chunks = [doc for source, text in sorted(docs.items()) for doc in hw4.chunk_document(source, text)]
    return hw4.build_index(chunks)


def historical_reason(index, question):
    parsed = hw4.parse_query(question)
    _, resolution = hw4.company_candidates(index, parsed["companies"])
    return hw4.abstention_reason(index, question, parsed, resolution)


class HistoricalAbstention(unittest.TestCase):
    def test_preserves_historical_prose_and_synonyms(self):
        cases = (
            ("total assets", "FY2022", "877.42",
             "<h3>Manufacturing footprint (USD millions)</h3>"
             "<p>At the end of the fiscal year immediately before the FY2023 comparative, group assets totalled 877.42.</p>"),
            ("operating income", "FY2021", "64.28",
             "<p>Consolidated operating earnings were USD 64.28 million for the year ended 31 December 2021.</p>"),
            ("long-term borrowings", "FY2021", "202.84",
             "<h3>Replaced credit facilities (USD millions)</h3>"
             "<p>Long-term debt for all consolidated entities was 202.84 at the end of FY2021.</p>"),
            ("net income", "FY2022", "69.58",
             "<p>The group earned profit after tax of USD 69.58 million for the full year ended 31 December 2022.</p>"),
            ("net property, plant and equipment", "FY2020", "471,250",
             "<h3>Equipment before consolidation (USD thousands)</h3>"
             "<p>In the FY2020 year-end consolidation the net carrying amount of property, plant and equipment was 471,250.</p>"),
            ("cash and cash equivalents", "FY2022", "86.4",
             "<h3>Liquidity at 31 December 2022 (USD <em>millions</em>)</h3>"
             "<p>Cash and cash equivalents stood at 86.4.</p>"),
        )
        for metric, year, printed, disclosure in cases:
            with self.subTest(metric=metric):
                index = index_with(disclosure)
                question = f"What was {COMPANY}'s {metric} in {year}, in USD millions?"
                self.assertTrue(hw4.retrieval_hit(hw4.retrieve(index, question), {
                    "evidence": [[["annual-2024.html", printed]]],
                }))

    def test_relative_evidence_veto_runs_before_original_historical_rejection(self):
        cases = (
            ("net cash from operating activities", "FY2021", "52.36",
             "<h3>Operating cash generation (USD millions)</h3>"
             "<p>For the year immediately preceding FY2022, cash from operating activities was 52.36.</p>"),
            ("depot rent refund", "FY2022", "2.18",
             "<p>The depot lease ended in the first full fiscal year following the FY2021 consolidation.</p>\n"
             "<p>On surrender, the landlord refunded the rent advance of USD 2.18 million.</p>"),
        )
        for metric, year, printed, note in cases:
            with self.subTest(metric=metric):
                index = index_with(note)
                question = f"What was {COMPANY}'s {metric} in {year}, in USD millions?"
                self.assertEqual(historical_reason(index, question), "unsupported_historical_period")
                self.assertTrue(hw4.retrieval_hit(hw4.retrieve(index, question), {
                    "evidence": [[["annual-2024.html", printed]]],
                }))

    def test_governance_year_does_not_show_historical_financial_coverage(self):
        index = index_with(governance="""<table><caption>Executive officers</caption>
<tr><th>Officer</th><th>Position</th><th>In role since</th></tr>
<tr><th scope="row">Ari Vela</th><td>Chief Financial Officer</td><td>2022</td></tr></table>
<p>The board charter was revised in FY2022.</p>""")
        questions = (
            f"What were {COMPANY}'s total assets at 31 December 2022, in USD millions?",
            f"What was {COMPANY}'s operating income when its Chief Financial Officer joined in FY2022, in USD millions?",
            f"What was {COMPANY}'s Chief Financial Officer compensation in FY2022, in USD millions?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(historical_reason(index, question))
                self.assertFalse(hw4.officer_intent(question))
                self.assertEqual(hw4.retrieve(index, question), [])

    def test_historical_officer_identity_and_tenure(self):
        index = index_with(governance="""<h3>Board appointments in FY2022</h3>
<p>At 31 December 2022 the role of Chief Financial Officer was held by Ari Vela.</p>
<p>In FY2022 Tessa Wynn served as Chief Executive Officer and Asha Flynn as board director.</p>
<p>At FY2022 year-end the CFO had served two full years.</p>""")
        for prompt, printed in (
            ("Who held {company}'s Chief Financial Officer role in FY2022?", "Ari Vela"),
            ("Which executive was Chief Executive Officer of {company} in FY2022?", "Tessa Wynn"),
            ("Who served as a board director at {company} in FY2022?", "Asha Flynn"),
            ("How many years had {company}'s CFO served by the end of FY2022?", "two full years"),
        ):
            with self.subTest(prompt=prompt):
                question = prompt.format(company=COMPANY)
                self.assertTrue(hw4.officer_intent(question))
                self.assertTrue(hw4.retrieval_hit(hw4.retrieve(index, question), {
                    "evidence": [[["annual-2024.html", printed], ["annual-2025.html", printed]]],
                }))
        missing = f"Who was {COMPANY}'s Chief Financial Officer in FY2020?"
        self.assertEqual(hw4.retrieve(index, missing), [])

    def test_prior_year_comparative_remains_retrievable(self):
        index = index_with()
        question = f"What were {COMPANY}'s total assets at 31 December 2023, in USD millions?"
        self.assertTrue(hw4.retrieval_hit(hw4.retrieve(index, question), {
            "evidence": [[["annual-2024.html", "788.1"]]],
        }))

    def test_ambiguous_relative_financial_amount_keeps_original_chunks(self):
        index = index_with("<h3>Refinancing (USD millions)</h3>"
                           "<p>At the time of the refinancing, assets totalled 711.4.</p>")
        question = f"What were {COMPANY}'s total assets at 31 December 2022, in USD millions?"
        ranked = hw4.retrieve(index, question)
        self.assertTrue(ranked)
        self.assertTrue(all(any(chunk is original for original in index.chunks) for chunk in ranked))

    def test_heading_scope_does_not_attach_to_unrelated_following_amount(self):
        cases = (
            ("<h3>Cash at FY2022 (USD millions)</h3><p>This year we reconciled cash. The amount was 51.3.</p>"),
            ("<h3>Cash at FY2022 (USD millions)</h3><div>Budget for the current year</div><p>It was 51.3.</p>"),
            ("<h3>Directors appointed in FY2022</h3><p>The current bonus pool was USD 12.3 million.</p>"),
        )
        for html in cases:
            with self.subTest(html=html):
                soup = hw4.BeautifulSoup(html, "html.parser")
                self.assertFalse(hw4.adjacent_evidence(hw4.heading_pairs(soup), 2024, 2022))


if __name__ == "__main__":
    unittest.main()
