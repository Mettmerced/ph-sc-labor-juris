"""Parser, classifier, and search tests. No network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ph_sc_labor_juris.chunk import chunk_text
from ph_sc_labor_juris.corpus import CaseCorpus, load_case_files
from ph_sc_labor_juris.docket import gr_key
from ph_sc_labor_juris.http_client import FetchError, HttpClient, decode_html
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

    def test_lawphil_index_accepts_the_later_row_shapes(self):
        page = """<html><body><table>
        <tr valign="top" bgcolor="#fbedfa">
        <td><a href="gr_160753_2004.html">G.R. No. 160753</a><br />September 30, 2004</td>
        <td>Jimmy L. Barnes <a class="vs">vs.</a> National Labor Relations Commission</td>
        </tr>
        <tr class="xy"><td> <a href="gr_193047_2014.html">G.R. No. 193047</a> <br />March 3, 2014</a> </td><td> Fil-Pride Shipping Company, Inc. <a class=vs>vs</a> Edgar A. Balasta </td><td> <a href="pdf/gr_193047_2014.pdf"><img src="p.png"></a></td></tr>
        <tr class="xy"><td> <a href="ac_6705_2006.html">A.C. No. 6705</a> <br />March 31, 2006 </td><td> Ruthie Lim-Santiago <a class="vs">vs.</a> Atty. Carlos B. Sagucio</td>
        <tr class="xy" class="xy"><td><a href="gr_192393_2019.html">G.R. No. 192393</a><br />March 27, 2019 </td><td> Fil-Estate Management, Inc. <a class=vs>vs.</a> Republic of the Philippines<br /><a class=vs>Concurring Opinion</a></td></tr>
        </table></body></html>"""
        rows = parse_lawphil_index(page, "https://lawphil.net/judjuris/juri2004/sep2004/sep2004.html")
        self.assertEqual([row.docket for row in rows], [
            "G.R. No. 160753",
            "G.R. No. 193047",
            "A.C. No. 6705",
            "G.R. No. 192393",
        ])
        self.assertEqual(rows[0].decided_on, "September 30, 2004")
        self.assertIn("National Labor Relations Commission", rows[0].title)
        self.assertNotIn("Concurring", rows[3].title)
        self.assertTrue(rows[1].url.endswith("gr_193047_2014.html"))

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

    def test_inner_blockquote_does_not_replace_the_decision(self):
        page = """<html><head><title>Printer Friendly</title></head><body>
        <h2>[ G.R. No. 112096, January 30, 1996 ]</h2>
        <h3>D E C I S I O N</h3>
        <p>The employee was illegally dismissed by the company after a POEA case.</p>
        <blockquote>A short quotation about wages in an earlier case.</blockquote>
        <blockquote>Another quotation that is not the whole decision.</blockquote>
        <p>The petition is granted.</p>
        <p>Source: Supreme Court E-Library</p>
        </body></html>"""
        text = html_to_text(page)
        self.assertIn("illegally dismissed", text)
        self.assertIn("petition is granted", text)
        self.assertIn("G.R. No. 112096", text)
        self.assertIn("short quotation", text)
        self.assertNotIn("Printer Friendly", text)
        self.assertNotIn("Supreme Court E-Library", text)


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


class HttpClientTests(unittest.TestCase):
    def test_read_timeout_is_a_fetch_error(self):
        from unittest.mock import patch

        client = HttpClient(delay=0, timeout=1)
        with patch("ph_sc_labor_juris.http_client.time.sleep"), patch(
            "ph_sc_labor_juris.http_client.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with self.assertRaises(FetchError) as raised:
                client.get("https://elibrary.judiciary.gov.ph/thebookshelf/showdocsfriendly/1/1")
        self.assertIn("timed out", str(raised.exception))


class DecodeTests(unittest.TestCase):
    def test_lawphil_is_cp1252_even_when_the_header_disagrees(self):
        raw = bytes([0x96])
        text = decode_html(raw, "iso-8859-1", url="https://lawphil.net/judjuris/juri1990/jan1990/jan1990.html")
        self.assertEqual(text, "\u2013")

    def test_elibrary_is_utf8(self):
        raw = "ñ".encode("utf-8")
        text = decode_html(raw, "iso-8859-1", url="https://elibrary.judiciary.gov.ph/thebookshelf/showdocsfriendly/1/1")
        self.assertEqual(text, "ñ")


class CorpusTests(unittest.TestCase):
    def test_index_loads_case_json_without_the_full_text_in_the_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = CaseCorpus(root / "cases")
            corpus.write(
                {
                    "gr_key": "GR-72654",
                    "docket": "G.R. Nos. 72654-61",
                    "title": "Alipio R. Ruga vs. National Labor Relations Commission",
                    "decided_on": "January 22, 1990",
                    "year": 1990,
                    "url": "https://example.test/ruga",
                    "source": "lawphil",
                    "text": (
                        "The Court held that the fishermen-crew were employees and were illegally dismissed. "
                        "The right-of-control test showed that the boat owner directed the fishing operations."
                    ),
                }
            )
            manifest = json.loads((root / "cases" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["count"], 1)
            self.assertNotIn("text", manifest["cases"][0])
            saved = json.loads((root / "cases" / "1990" / "GR-72654.json").read_text(encoding="utf-8"))
            self.assertIn("illegally dismissed", saved["text"])

            connection = connect(root / "corpus.sqlite")
            self.assertEqual(load_case_files(connection, root / "cases"), 1)
            self.assertGreater(build_index(connection), 0)
            rows = search(connection, "Were the fishermen employees or partners in a joint venture?")
            self.assertTrue(rows)
            self.assertEqual(rows[0]["gr_key"], "GR-72654")
            connection.close()


class ChunkTests(unittest.TestCase):
    def test_long_text_is_split(self):
        pieces = chunk_text(("Paragraph about backwages. " * 80) + "\n\n" + ("More. " * 80), size=500, overlap=50)
        self.assertGreater(len(pieces), 1)


if __name__ == "__main__":
    unittest.main()
