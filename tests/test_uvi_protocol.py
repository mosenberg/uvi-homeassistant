"""Offline regression tests using entirely synthetic Genero responses."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "uvi_service"
FIXTURES = ROOT / "tests" / "fixtures"
# Load the transport/parser without importing Home Assistant's integration entry.
package = types.ModuleType("uvi_protocol_test")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("uvi_protocol_test.api", PACKAGE / "api.py")
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
# Parsing tests do not use the HTTP transport or require aiohttp to be installed.
with patch.dict(sys.modules, {"aiohttp": types.ModuleType("aiohttp")}):
    spec.loader.exec_module(api)


class ProtocolTests(unittest.TestCase):
    def test_full_login_form_includes_first_month(self):
        state = {}
        months = api.apply_response((FIXTURES / "login-response.txt").read_text(), state)
        self.assertEqual(months[0], "Februar 2026")
        row = api.record(state)
        self.assertEqual(row["month"], "2026-02-01")
        self.assertEqual(row["heating_kwh"], "123.000")
        self.assertEqual(row["coldwater_m3"], "2.500")

    def test_delta_retains_zero_and_unchanged_values(self):
        state = {"month": "Juli 2025", "heating_kwh": "0,000",
                 "warmwater_kwh": "58,150", "coldwater_m3": "2,000"}
        api.apply_response('om 6 {{un 3 {{value "Juni 2025"}}} {un 605 {{value "3,000"}}}}', state)
        row = api.record(state)
        self.assertEqual(row["heating_kwh"], "0.000")
        self.assertEqual(row["warmwater_m3"], "1.000")
        self.assertEqual(row["coldwater_m3"], "3.000")

    def test_empty_delta_keeps_first_month(self):
        state = {}
        api.apply_response((FIXTURES / "login-response.txt").read_text(), state)
        before = api.record(state)
        api.apply_response("om 5 {}", state)
        self.assertEqual(api.record(state), before)

    def test_explicit_empty_clears_value(self):
        state = {"month": "Januar 2026", "heating_kwh": "100,000"}
        api.apply_response('om 7 {{un 85 {{value ""}}}}', state)
        self.assertIsNone(api.record(state)["heating_kwh"])

    def test_quoted_braces_are_not_structure(self):
        state = {}
        api.apply_response('om 0 {{un 8 {{value "a {brace} and \\"quote\\""}}}}', state)
        self.assertEqual(state, {})


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_url_without_token(self):
        requests = []

        class Response:
            status = 403

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class Session(Response):
            def __init__(self, **kwargs):
                pass

            def request(self, method, url, **kwargs):
                requests.append(url)
                return Response()

        fake_http = types.SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **kwargs: None,
                                          ClientError=RuntimeError)
        for token in (None, "", "example-token"):
            credentials = dict(property_id="example", email="test@example.invalid", password="test-password")
            if token is not None:
                credentials["launch_token"] = token
            with patch.object(api, "aiohttp", fake_http), self.assertRaises(api.InvalidAuth):
                await api.UviApi(credentials).fetch()
            query = parse_qs(urlsplit(requests[-1]).query)
            self.assertEqual(len(query["Arg"]), 2)
            self.assertEqual(query.get("djxkaiemglvvihukvsobuyiyby"), [token] if token else None)

    async def test_complete_handshake_and_first_month(self):
        login = (FIXTURES / "login-response.txt").read_text()
        replies = ["<html/>", "meta Connection {}", "om 0 {}", "om 1 {}", "om 2 {}", "om 3 {}",
                   login, (FIXTURES / "january-response.txt").read_text()]
        requests = []

        class Response:
            status = 200
            headers = {"X-FourJs-Id": "abc123"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def text(self):
                return replies.pop(0)

        class Session(Response):
            def __init__(self, **kwargs):
                pass

            def request(self, method, url, **kwargs):
                requests.append((method, url, kwargs.get("data")))
                return Response()

        fake_http = types.SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **kwargs: None,
                                          ClientError=RuntimeError)
        credentials = dict(property_id="example", email="test@example.invalid", password="test-password", launch_token="dummy")
        with patch.object(api, "aiohttp", fake_http):
            rows = await api.UviApi(credentials).fetch()
        self.assertEqual([row["month"] for row in rows], ["2026-01-01", "2026-02-01"])
        self.assertEqual(rows[1]["heating_kwh"], "123.000")
        self.assertEqual(rows[0]["heating_kwh"], "200.000")
        self.assertEqual(len(requests), 8)
        self.assertIn('event _om 3{}{{ConfigureEvent 0{{idRef "40"}', requests[6][2])
        self.assertTrue(requests[-1][1].endswith("pageId=6"))
        self.assertFalse(replies)


if __name__ == "__main__":
    unittest.main()
