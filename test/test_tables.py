import json
import unittest
from pathlib import Path

import hw4


class TableRendering(unittest.TestCase):
    def test_actual_years_units_and_overlapping_row_names(self):
        html = """<table><caption>Figures (USD millions)</caption>
        <thead><tr><th></th><th>2031</th><th>2030</th></tr></thead>
        <tr><th scope="row">Debt</th><td>(1,234.00)</td><td>0.0</td></tr>
        <tr><td>Debt due</td><td>1,000</td><td>2.50</td></tr></table>"""
        lines = hw4.table_to_text(html).splitlines()
        self.assertIn("Figures (USD millions)", lines)
        self.assertIn("Debt | 2031: (1,234.00) | 2030: 0.0", lines)
        self.assertIn("Debt due | 2031: 1,000 | 2030: 2.50", lines)

    def test_grouped_headers_section_and_spanning_value(self):
        table = """<table><thead>
        <tr><th rowspan="2">Officer</th><th colspan="2">Term</th><th>Office</th></tr>
        <tr><td>Start</td><td>End</td><td>Location</td></tr></thead>
        <tbody><tr><th scope="row" colspan="4">Executive committee</th></tr>
        <tr><th>Ada</th><td></td><td>2030</td><td>Hong Kong</td></tr>
        <tr><td>Ben</td><td colspan="2">Pending</td><td>Seoul</td><td>Observer</td></tr>
        </tbody></table>"""
        lines = hw4.table_to_text(table).splitlines()
        self.assertIn("Executive committee", lines)
        self.assertIn("Ada | Term End: 2030 | Office Location: Hong Kong", lines)
        self.assertIn("Ben | Term Start / Term End: Pending | Office Location: Seoul | Observer", lines)

    def test_wide_rows_repeat_the_label_with_each_continuation(self):
        value = "A" * 190
        table = (f"<table><tr><th>Name</th><th>Role</th><th>Location</th></tr>"
                 f"<tr><td>Director</td><td>{value}</td><td>{value}</td></tr></table>")
        lines = hw4.table_to_text(table).splitlines()
        self.assertIn(f"Director | Role: {value}", lines)
        self.assertIn(f"Director | Location: {value}", lines)
        self.assertTrue(all(len(line) <= 400 for line in lines))

    def test_each_public_fixture(self):
        tables = json.loads((Path(hw4.__file__).parent / "public_test/tables.json").read_text())
        for fixture in tables:
            with self.subTest(caption=fixture["caption"]):
                self.assertEqual(hw4.table_score(hw4.table_to_text(fixture["html"]), fixture), 1)

    def test_document_replaces_each_table_in_place_and_keeps_its_source(self):
        for filename, name, amount in [("one.html", "Juniper", "7.00"),
                                       ("two.html", "Elm", "(3.10)")]:
            with self.subTest(filename=filename):
                table = (f"<table><caption>{name} (USD)</caption><tr><th></th><th>2030</th></tr>"
                         f"<tr><td>Debt</td><td>{amount}</td></tr></table>")
                html = f"<title>Annual Report 2030</title><h1>{name}</h1>Start{table}Middle{table}End"
                chunk, = hw4.chunk_document(filename, html)
                rendered = f"{name} (USD)\n2030\nDebt | 2030: {amount}"
                self.assertEqual(chunk.page_content,
                                 f"Annual Report 2030{name}Start\n{rendered}\nMiddle\n{rendered}\nEnd")
                self.assertEqual(chunk.metadata, dict(source=filename, company=name,
                                                      fiscal_year=2030, doc_type="annual_report"))
