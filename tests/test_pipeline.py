"""Parser, classifier, and search tests. No network."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ph_sc_labor_juris.chunk import chunk_text
from ph_sc_labor_juris.docket import gr_key
from ph_sc_labor_juris.index import build_index, search
from ph_sc_labor_juris.labor import classify, title_is_candidate
from ph_sc_labor_juris.parse import (
    html_to_text,
    parse_elib_index,
    parse_lawphil_index,
)
from ph_sc_labor_juris.store import connect, save_decision, upsert_listing

FIXTURES = Path(__file__).parent / "fixtures"


class DocketTests(unittest.TestCase):
    def test_consolidated_docket_uses_the_first_number(self):
        self.assertEqual(gr_key("G.R. Nos. 72654-61"), "GR-72654")

    def test_legacy_l_number(self):
        self.assertEqual(gr_key("G.R. No. L-45210"), "GR-L-45210")


class LaborTests(unittest.TestCase):
    def test_nlrc_title_is_a_labor_case(self):
        is_labor, _reason = classify(
            "Alipio R. Ruga vs. National Labor Relations Commission",
            "The fishermen were illegally dismissed.",
        )
        self.assertTrue(is_labor)

    def test_party_names_need_labor_discussion_in_the_text(self):
        is_labor, _reason = classify(
            "Pacific Mills, Inc. vs. Juan dela Cruz",
            "The Labor Arbiter found illegal dismissal and awarded backwages under the Labor Code.",
        )
        self.assertTrue(is_labor)

    def test_a_criminal_case_is_not_labor(self):
        is_labor, _reason = classify(
            "People of the Philippines vs. Reynaldo R. Rosell",
            "The accused was convicted of homicide. The employee of the shop testified.",
        )
        self.assertFalse(is_labor)
        self.assertFalse(title_is_candidate("People of the Philippines vs. Reynaldo R. Rosell"))


class ParseTests(unittest.TestCase):
    def test_lawphil_index(self):
        page = (FIXTURES / "lawphil_index.html").read_text(encoding="utf-8")
        rows = parse_lawphil_index(page, "https://lawphil.net/judjuris/juri1990/jan1990/jan1990.html")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].docket, "G.R. Nos. 72654-61")
        self.assertIn("National Labor Relations Commission", rows[1].title)
        self.assertTrue(rows[1].url.endswith("gr_72654_1990.html"))

    def test_elibrary_index(self):
        page = (FIXTURES / "elib_index.html").read_text(encoding="utf-8")
        rows = parse_elib_index(page)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].elib_id, "42001")
        self.assertEqual(rows[0].decided_on, "June 18, 1996")

    def test_decision_text_drops_the_site_watermark(self):
        page = (FIXTURES / "decision.html").read_text(encoding="utf-8")
        text = html_to_text(page)
        self.assertIn("illegally dismissed", text)
        self.assertNotIn("Lawphil", text)
        self.assertNotIn("watermark", text)


class SearchTests(unittest.TestCase):
    def test_search_returns_the_labor_passage(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = connect(Path(folder) / "corpus.sqlite")
            upsert_listing(
                connection,
                gr_key="GR-72654",
                docket="G.R. Nos. 72654-61",
                title="Alipio R. Ruga vs. National Labor Relations Commission",
                decided_on="January 22, 1990",
                year=1990,
                url="https://example.test/ruga",
                source="lawphil",
                elib_id=None,
            )
            save_decision(
                connection,
                "GR-72654",
                "The Court held that the fishermen-crew were employees and were illegally dismissed. "
                "The right-of-control test showed that the boat owner directed the fishing operations.",
                True,
                "test",
            )
            connection.commit()
            self.assertGreater(build_index(connection), 0)
            rows = search(connection, "Were the fishermen employees or partners in a joint venture?")
            self.assertTrue(rows)
            self.assertEqual(rows[0]["gr_key"], "GR-72654")
            self.assertIn("illegally dismissed", rows[0]["text"])
            connection.close()


class ChunkTests(unittest.TestCase):
    def test_long_text_is_split(self):
        pieces = chunk_text(("Paragraph about backwages. " * 80) + "\n\n" + ("More. " * 80), size=500, overlap=50)
        self.assertGreater(len(pieces), 1)


if __name__ == "__main__":
    unittest.main()
