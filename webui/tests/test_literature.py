import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from danus.integrations import literature as lit
from danus.integrations.literature_log import read_events
from danus.gateway import server as gateway


class LiteratureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            "DANUS_LITERATURE_CACHE": str(self.root / "cache"),
            "DANUS_PROJECT_DIR": str(self.root), "DANUS_ROLE": "worker",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_partial_provider_outage_is_reported_and_success_cached(self):
        with patch.object(lit, "_search_arxiv", side_effect=TimeoutError("offline")), \
             patch.object(lit, "_search_crossref", return_value=[{"title": "Real record", "doi": "10.test/paper"}]) as crossref, \
             patch("danus.integrations.iacr.search", return_value=[]):
            out = lit.search_papers("graph", 2)
            self.assertEqual(out["count"], 1)
            self.assertIn("arxiv", out["errors"])
            lit.search_papers("graph", 2)
            self.assertEqual(crossref.call_count, 1)

    def test_arxiv_source_metadata_and_formula_are_preserved(self):
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.01234v2</id><title>A real title</title><author><name>A Author</name></author><published>2024-01-02T00:00:00Z</published><summary>The abstract.</summary></entry></feed>'''
        record = lit._arxiv_records(atom)[0]
        self.assertEqual(record["url"], "https://arxiv.org/abs/2401.01234v2")
        self.assertEqual(record["authors"], ["A Author"])
        self.assertEqual(record["year"], "2024")
        text = lit._html_text(b'<html><article><p>Theorem</p><math alttext="x^2 + y^2">xxyy</math><script>bad()</script></article></html>')
        self.assertIn("$x^2 + y^2$", text)
        self.assertNotIn("bad()", text)

    def test_read_blocks_local_and_unrelated_urls_before_network(self):
        bad = ["http://127.0.0.1/admin", "https://example.com/paper", "https://arxiv.org.evil/abs/2401.01234", "https://user@arxiv.org/abs/2401.01234", "https://arxiv.org:444/abs/2401.01234", "../../config", "https://arxiv.org/abs/../config"]
        with patch.object(lit, "_download") as download:
            for value in bad:
                self.assertIn("error", lit.read_paper(value))
            download.assert_not_called()
        self.assertEqual(lit._paper_id("https://arxiv.org/pdf/math/0309136.pdf"), "math/0309136")

    def test_paper_read_is_paginated_and_shared_cache_avoids_refetch(self):
        with patch.object(lit, "_paper_document", return_value={"text": "A" * 4000, "url": "https://arxiv.org/html/2401.01234", "source_format": "html"}) as fetch:
            first = lit.read_paper("2401.01234", 0, 1000)
            self.assertEqual(first["next_offset"], 1000)
            second = lit.read_paper("2401.01234", first["next_offset"], 24000)
            self.assertIsNone(second["next_offset"])
            self.assertEqual(len(second["text"]), 3000)
            self.assertEqual(fetch.call_count, 1)

    def test_source_history_records_workers_but_verifier_stays_read_only(self):
        result = {"results": [{"title": "A paper", "arxiv_id": "2401.01234", "url": "https://arxiv.org/abs/2401.01234"}], "count": 1}
        with patch.object(lit, "search_papers", return_value=result):
            gateway.search_papers("graph")
            events = read_events(self.root)
            self.assertEqual(events[0]["query"], "graph")
            self.assertEqual(events[0]["results"][0]["title"], "A paper")
            with patch.dict(os.environ, {"DANUS_ROLE": "verifier"}):
                gateway.search_papers("private verification query")
            self.assertEqual(len(read_events(self.root)), 1)
        self.assertFalse((self.root / "fact_graph").exists())

    def test_paper_failure_does_not_claim_success_or_fabricate_text(self):
        with patch.object(lit, "_paper_document", side_effect=ValueError("paper unavailable")):
            result = lit.read_paper("2401.01234")
            self.assertIn("paper unavailable", result["error"])
            self.assertEqual(result["text"], "")
            self.assertNotIn("content_level", result)

    def test_openapi_only_exposes_read_only_literature_tools(self):
        from research_api import research_app
        schema = research_app.openapi()
        self.assertEqual(set(schema["paths"]), {"/search", "/read", "/theorems", "/web", "/status"})
        for path in schema["paths"].values():
            self.assertEqual(set(path), {"get"})

    def test_iacr_source_and_metadata_search(self):
        from danus.integrations import iacr
        with iacr._connect() as db:
            iacr._apply_page(db, [{"id": "2025/123", "title": "Lattice proof systems", "authors": '["Alice Example"]',
                "abstract": "Zero knowledge proofs over lattices", "categories": "Foundations", "published": "2025-01-02", "updated": "2025-01-02", "rights": '[]'}])
            import time
            iacr._save_state(db, last_success=time.time())
        out = lit.search_papers("lattice", source="iacr")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["eprint_id"], "2025/123")
        self.assertEqual(out["results"][0]["content_level"], "abstract")
        self.assertEqual(lit.search_papers("https://eprint.iacr.org/2025/123.pdf", source="iacr")["count"], 1)
        self.assertEqual(lit.search_papers("' OR 1=1;--", source="iacr")["count"], 0)

    def test_iacr_oai_parsing_withdrawals_and_unexpected_html(self):
        from danus.integrations import iacr
        xml = b'''<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><ListRecords><record><header><identifier>oai:eprint.iacr.org:2025/1</identifier><datestamp>2025-01-01</datestamp></header><metadata><dc:title>A theorem</dc:title><dc:creator>Author One</dc:creator><dc:description>An abstract</dc:description><dc:date>2025-01-01</dc:date></metadata></record><resumptionToken>next-cursor</resumptionToken></ListRecords></OAI-PMH>'''
        rows, token = iacr._parse_page(xml)
        self.assertEqual(token, "next-cursor")
        self.assertEqual(json.loads(rows[0]["authors"]), ["Author One"])
        with iacr._connect() as db:
            iacr._apply_page(db, rows)
            rows[0]["title"] = "Updated theorem"
            iacr._apply_page(db, rows)
            self.assertEqual(db.execute("select count(*) from paper_fts").fetchone()[0], 1)
            iacr._apply_page(db, [{"id": "2025/1", "deleted": True}])
            self.assertEqual(db.execute("select count(*) from papers").fetchone()[0], 0)
            self.assertEqual(db.execute("select count(*) from paper_fts").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            iacr._parse_page(b'<html><p>Service unavailable</p></html>')

    def test_iacr_uses_only_advertised_metadata_endpoint(self):
        with self.assertRaisesRegex(ValueError, "metadata interface only"):
            lit._download("https://eprint.iacr.org/2025/1.pdf")
        with self.assertRaisesRegex(ValueError, "metadata interface only"):
            lit._download("https://eprint.iacr.org/search?q=lattice")


if __name__ == "__main__":
    unittest.main()
