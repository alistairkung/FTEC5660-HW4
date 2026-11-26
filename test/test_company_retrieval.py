import unittest
from unittest.mock import patch

import hw4


def chunk(company, source, text="cash assets"):
    return hw4.Document(page_content=text, metadata={"company": company, "source": source})


def retrieve_for(index, question, *companies):
    with patch("hw4.parse_query", return_value={"companies": list(companies)}):
        return hw4.retrieve(index, question)


class CompanyRetrieval(unittest.TestCase):
    def test_exact_company_match_preserves_original_duplicate_text_chunks(self):
        first = chunk("Alder Group Ltd.", "a")
        second = chunk("ALDER  GROUP LTD", "b")
        unrelated = chunk("Alder Group Holdings", "c")
        index = hw4.build_index([first, second, unrelated])
        result = retrieve_for(index, "cash", "alder group")
        self.assertEqual(len(result), 2)
        self.assertIs(result[0], second)
        self.assertIs(result[1], first)

    def test_comparison_uses_both_companies_without_reserving_slots(self):
        fir = [chunk("Fir Group", str(i), "needle " * 2) for i in range(6)]
        elm = chunk("Elm Group", "elm")
        other = [chunk("Other", str(i), "background") for i in range(12)]
        index = hw4.build_index([*fir, elm, *other])
        question = "Which held more needle: Fir Group or Elm Group?"
        actual = hw4.retrieve(index, question)
        self.assertEqual(len(actual), 5)
        self.assertTrue(all(any(doc is original for original in fir) for doc in actual))
        self.assertCountEqual(hw4.retrieve(hw4.build_index([fir[0], elm, *other]), question),
                         [fir[0], elm])

    def test_unresolved_ambiguous_or_missing_subject_preserves_global_order(self):
        docs = [chunk("Alder Group Inc.", "a"), chunk("Alder Group Ltd.", "b"),
                chunk("Alder Group Holdings", "c"), chunk("Willow Group", "d")]
        index = hw4.build_index(docs)
        expected = index.ranker.get_top_n(["cash"], docs)
        for subjects in [(), ("Alder",), ("Alder Group",), ("Missing", "Willow Group")]:
            with self.subTest(subjects=subjects):
                self.assertEqual(retrieve_for(index, "cash", *subjects), expected)

    def test_and_in_name_and_unaltered_parser_fallback(self):
        docs = [chunk("Reed and Vale", "reed"), chunk("Willow Group", "willow"),
                chunk("Other", "other")]
        index = hw4.build_index(docs)
        question = "Which had more assets: Reed and Vale or Willow Group?"
        self.assertEqual(hw4.retrieve(index, question),
                         index.ranker.get_top_n(question.lower().split(), docs))
        self.assertEqual(hw4.retrieve(index, "How much did willow group earn?"),
                         index.ranker.get_top_n("how much did willow group earn?".split(), docs))
        self.assertEqual(retrieve_for(index, question, "Reed and Vale", "Willow Group"),
                         [doc for doc in index.ranker.get_top_n(question.lower().split(), docs)
                          if doc is not docs[2]])

    def test_global_scores_and_tie_order_are_used_for_eligible_chunks(self):
        docs = [chunk("Fir Group" if i % 2 else "Other", str(i), text)
                for i, text in enumerate(["cash", "cash assets", "asset"] * 8)]
        index = hw4.build_index(docs)
        question = "cash assets"
        tokens = question.split()
        reference = hw4.BM25Okapi([doc.page_content.lower().split() for doc in docs])
        expected = [doc for doc in reference.get_top_n(tokens, docs, len(docs))
                    if doc.metadata["company"] == "Fir Group"][:5]
        for _ in range(2):
            actual = retrieve_for(index, question, "Fir Group")
            self.assertEqual([id(doc) for doc in actual], [id(doc) for doc in expected])
            self.assertEqual(list(index.ranker.get_scores(tokens)), list(reference.get_scores(tokens)))

    def test_empty_and_unscored_indexes(self):
        self.assertEqual(hw4.retrieve(hw4.build_index([]), "What did Fir Group earn?"), [])
        first, second = chunk("Fir Group", "a", ""), chunk("Other", "b", "")
        self.assertEqual(retrieve_for(hw4.build_index([first, second]), "cash", "Fir Group"), [first])
