import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from danus.integrations import literature, matlas, search_settings as settings
from danus.gateway import server as gateway


class SearchSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.a, self.b = self.projects / "alpha", self.projects / "beta"
        self.a.mkdir(parents=True); self.b.mkdir()
        self.env = patch.dict(os.environ, {
            "DANUS_LITERATURE_CACHE": str(self.root / "cache"),
            "DANUS_SEARCH_SETTINGS_FILE": str(self.root / "search.json"),
            "DANUS_AGENTS_ROOT": str(self.projects), "DANUS_PROJECT_DIR": str(self.a),
            "DANUS_ROLE": "worker", "DANUS_SEARCH_PROJECT_DIR": "",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_disabled_tools_make_no_network_requests_even_with_cached_data(self):
        settings.write_project(self.a, {**settings.DEFAULT, "enabled": False})
        with patch.object(literature, "_download") as download, \
             patch.object(literature, "_cached") as cache, \
             patch("httpx.get") as web, patch("urllib.request.urlopen") as theorem:
            for result in [gateway.search_papers("graph"), gateway.search_web("graph"),
                           gateway.read_paper("2303.08774"), gateway.search_arxiv_theorems("graph")]:
                self.assertTrue(result["disabled"])
            for mock in (download, cache, web, theorem):
                mock.assert_not_called()

    def test_project_defaults_overrides_and_chat_are_independent(self):
        settings.write_global("danus", {**settings.DEFAULT, "enabled": False})
        settings.write_project(self.b, settings.DEFAULT)
        self.assertFalse(settings.effective("danus", self.a)["enabled"])
        self.assertTrue(settings.effective("danus", self.b)["enabled"])
        self.assertTrue(settings.effective("chat")["enabled"])
        settings.write_project(self.b, None)
        self.assertFalse(settings.effective("danus", self.b)["enabled"])
        self.assertTrue(settings.effective("danus", self.b)["inherited"])

    def test_deselected_source_is_not_called_or_used_as_fallback(self):
        settings.write_project(self.a, {"enabled": True, "web_engines": ["bing"], "paper_sources": ["arxiv"]})
        with patch.object(literature, "_search_arxiv", return_value=[{"title": "A"}]) as arxiv, \
             patch.object(literature, "_search_crossref") as crossref, \
             patch("danus.integrations.iacr.search") as iacr, patch.object(literature, "_web_provider") as web:
            self.assertEqual(gateway.search_papers("a")["count"], 1)
            self.assertTrue(gateway.search_papers("a", source="iacr")["disabled"])
            self.assertTrue(gateway.search_web("a", engine="google")["disabled"])
            arxiv.assert_called_once(); crossref.assert_not_called(); iacr.assert_not_called(); web.assert_not_called()

    def test_unknown_sources_rejected_and_broken_settings_fail_closed(self):
        with self.assertRaises(ValueError):
            settings.write_global("chat", {**settings.DEFAULT, "web_engines": ["unapproved"]})
        (self.a / "search-settings.json").write_text("[]")
        self.assertFalse(settings.effective("danus", self.a)["enabled"])
        self.assertIn("error", settings.effective("danus", self.a))

    def test_scoped_main_and_verifier_respect_project_choice(self):
        settings.write_project(self.b, {**settings.DEFAULT, "enabled": False})
        with patch.dict(os.environ, {"DANUS_ROLE": "main"}):
            self.assertFalse(gateway.get_search_settings(project="beta")["enabled"])
            self.assertTrue(gateway.get_search_settings(project="alpha")["enabled"])
        with patch.dict(os.environ, {"DANUS_ROLE": "verifier", "DANUS_SEARCH_PROJECT_DIR": str(self.b)}):
            self.assertTrue(gateway.search_web("q")["disabled"])
        self.assertFalse((self.b / "literature").exists())

    def test_verifier_request_passes_validated_project_and_rejects_escape(self):
        from danus.verify import service
        with patch.object(service, "run_prechecks", return_value=None), \
             patch.object(service, "_allocate_run_id", return_value="test"), \
             patch.object(service, "run_codex_verification", return_value={"verdict": "correct"}) as run:
            service.verify(service.VerifyRequest(statement="s", proof="p", search_project="beta"))
            self.assertEqual(run.call_args.kwargs["search_project_dir"], str(self.b))
        with self.assertRaises(ValueError):
            service.VerifyRequest(statement="s", proof="p", search_project="../beta")

    def test_chat_http_tool_and_native_search_share_off_switch(self):
        import server
        settings.write_global("chat", {**settings.DEFAULT, "enabled": False})
        with patch("httpx.get") as network:
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
                    for path in ["/research/web?query=test", "/research/search?query=test", "/research/theorems?query=test", "/research/read?arxiv_id=2303.08774", "/api/search/web?q=test"]:
                        r = await c.get(path)
                        self.assertEqual(r.status_code, 200)
                        self.assertTrue(r.json()["disabled"], path)
            asyncio.run(run())
            network.assert_not_called()

    def test_project_switch_can_be_set_at_creation_before_start(self):
        import server
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
                r = await c.post("/api/danus/projects", json={"name": "offline-test", "problem": "Test only", "search_mode": "off"})
                self.assertEqual(r.status_code, 200, r.text)
                r = await c.get("/api/danus/projects/offline-test/search-settings")
                self.assertFalse(r.json()["enabled"])
                self.assertFalse(r.json()["inherited"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
