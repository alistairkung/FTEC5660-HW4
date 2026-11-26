"""Exercise the composed retrieval path through the lecturer's student functions."""

import unittest

import hw4


def annual(company: str, body: str, filing: int = 2039) -> str:
    return f"<title>Annual Report {filing}</title>\n<h1>{company}</h1>\n{body}"


def regional_table(caption: str = "Revenue by region (USD millions)") -> str:
    return f"""<table><caption>{caption}</caption>
<tr><th>Region</th><th>FY2039</th><th>FY2038</th></tr>
<tr><td>Amber Coast</td><td>336.8</td><td>278.4</td></tr>
<tr><td>Western Shelf</td><td>442.1</td><td>391.8</td></tr></table>"""


class CombinedRetrievalTests(unittest.TestCase):
    def test_retrieves_prose_and_narrows_a_comparative_cell_from_the_same_index(self):
        company = "Tamarind Coil"
        audit = f"Which accounting firm signed off on {company}'s accounts for FY2039?"
        revenue = f"How much revenue did {company} generate in Amber Coast in FY2038, in USD millions?"
        corpus = {
            "filing.html": annual(company, regional_table() +
                                  "\n<h2>Independent auditor</h2>\n<p>Rowan Fen LLP audited the FY2039 accounts.</p>"),
            **{f"agenda-{position}.html": annual(company, f"<p>Agenda: {audit} See index.</p>")
               for position in range(6)},
            **{f"other-{position}.html": annual(f"Other Issuer {position}", "<p>Inventory and contracts.</p>")
               for position in range(14)},
        }
        chunks = [chunk for source, html in corpus.items() for chunk in hw4.chunk_document(source, html)]
        index = hw4.build_index(chunks)

        prose = hw4.retrieve(index, audit)
        self.assertIn("Rowan Fen LLP", prose[0].page_content)
        self.assertIn("Western Shelf", prose[0].page_content)
        cells = hw4.retrieve(index, revenue)
        self.assertTrue(any(chunk.page_content == "Revenue by region (USD millions)\nAmber Coast | FY2038: 278.4"
                            for chunk in cells))
        for result in (prose, cells):
            self.assertLessEqual(len(result), 5)
            self.assertTrue(all(any(chunk is original for original in chunks) for chunk in result))
        self.assertEqual(hw4.retrieve(index, "What was Copper Spool's revenue in FY2038?"), [])

    def test_parent_preserves_scale_or_currency_basis_available_only_in_prose(self):
        company = "Juniper Array"
        stem = f"How much revenue did {company} generate in Amber Coast in FY2038"
        for caption, note, question in (
            ("Revenue by region", "The table figures are in thousands of US dollars.",
             stem + ", in USD millions?"),
            ("Revenue by region (USD millions)", "The FY2038 comparison is presented at constant currency.",
             stem + " on a constant-currency basis, in USD millions?"),
        ):
            with self.subTest(note=note):
                html = annual(company, f"<p>{note}</p>\n" + regional_table(caption))
                chunks = hw4.chunk_document("accounts.html", html)
                retrieved = hw4.retrieve(hw4.build_index(chunks), question)
                self.assertTrue(any(note in chunk.page_content and "278.4" in chunk.page_content
                                    for chunk in retrieved))

    def test_currency_basis_present_in_caption_survives_narrowing(self):
        company = "Juniper Array"
        caption = "Revenue by region (USD millions; FY2038 presented at constant currency)"
        chunks = hw4.chunk_document("accounts.html", annual(company, regional_table(caption)))
        question = (f"How much revenue did {company} generate in Amber Coast in FY2038 "
                    "on a constant-currency basis, in USD millions?")
        retrieved = hw4.retrieve(hw4.build_index(chunks), question)
        self.assertTrue(any(chunk.page_content == f"{caption}\nAmber Coast | FY2038: 278.4"
                            for chunk in retrieved))
