"""Check fresh setup and upgrades of the package-managed research assistant."""
import copy
import json
import unittest
from unittest.mock import patch

import httpx
import configure_research


class ResearchConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.model = None
        self.created = []
        self.updated = []
        self.connections = [{"info": {"id": "unrelated-tool"}, "url": "http://example.invalid"}]
        real_client = httpx.Client
        transport = httpx.MockTransport(self.handle)
        self.client_patch = patch.object(
            configure_research.httpx, "Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        )
        self.preferences_patch = patch.object(
            configure_research.search_settings, "effective", return_value={"enabled": True}
        )
        self.sync_patch = patch.object(configure_research, "sync_chat_preferences")
        for active in (self.client_patch, self.preferences_patch, self.sync_patch):
            active.start()
            self.addCleanup(active.stop)

    def handle(self, request):
        path = request.url.path
        data = json.loads(request.content) if request.content else None
        if path == "/api/v1/auths/signin":
            response = {"token": "test-token"}
        elif path == "/api/v1/configs/import":
            response = {}
        elif path == "/api/v1/configs/tool_servers":
            if request.method == "POST":
                self.connections = data["TOOL_SERVER_CONNECTIONS"]
            response = {"TOOL_SERVER_CONNECTIONS": self.connections}
        elif path == "/api/v1/models":
            response = {"data": [self.model] if self.model else []}
        elif path == "/api/v1/models/model":
            response = self.model
        elif path in ("/api/v1/models/create", "/api/v1/models/model/update"):
            self.model = copy.deepcopy(data)
            (self.created if path.endswith("create") else self.updated).append(copy.deepcopy(data))
            response = self.model
        elif path == "/api/v1/configs/models":
            response = {"DEFAULT_MODELS": "local-research"}
        elif path == "/api/v1/retrieval/config":
            response = {"web": {"WEB_SEARCH_ENGINE": "searxng"}}
        else:
            raise AssertionError(f"Unexpected request: {request.method} {path}")
        return httpx.Response(200, json=response)

    def assert_english_assistant(self):
        self.assertEqual(self.model["name"], "Local Research Assistant")
        self.assertIn("Respond in English by default", self.model["params"]["system"])
        self.assertIn("get_search_settings", self.model["params"]["system"])
        self.assertIn("source=iacr", self.model["params"]["system"])
        self.assertEqual(self.model["meta"]["danus_research_version"], 4)
        self.assertEqual(self.connections[0]["info"]["id"], "unrelated-tool")
        self.assertEqual(self.connections[1]["info"]["name"], "Web and Paper Search")

    def test_fresh_setup_creates_english_assistant(self):
        with patch.dict("os.environ", {"MODEL_NAME": "test-local-model"}):
            configure_research.configure()
        self.assert_english_assistant()
        self.assertEqual(self.model["base_model_id"], "test-local-model")
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.updated, [])

    def test_upgrade_refreshes_language_and_keeps_unrelated_settings(self):
        self.model = {
            "id": "local-research", "name": "\u672c\u6a5f\u7814\u7a76\u52a9\u7406",
            "base_model_id": "existing-model",
            "params": {"system": "\u9810\u8a2d\u4ee5\u7e41\u9ad4\u4e2d\u6587\u56de\u7b54", "temperature": 0.25},
            "meta": {"danus_research_version": 3, "capabilities": {"file_upload": True},
                     "toolIds": ["server:danus-literature", "custom-tool"]},
        }
        configure_research.configure()
        self.assert_english_assistant()
        self.assertEqual(self.model["base_model_id"], "existing-model")
        self.assertEqual(self.model["params"]["temperature"], 0.25)
        self.assertEqual(self.model["meta"]["capabilities"], {"file_upload": True})
        self.assertEqual(self.model["meta"]["toolIds"], ["server:danus-literature", "custom-tool"])
        self.assertNotIn("\u7e41\u9ad4\u4e2d\u6587", self.model["params"]["system"])
        self.assertEqual(len(self.updated), 1)
        configure_research.configure()
        self.assertEqual(len(self.updated), 1, "Repeated setup must not overwrite an upgraded assistant")


if __name__ == "__main__":
    unittest.main()
