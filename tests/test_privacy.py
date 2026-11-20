"""Regression checks for error and debug output with synthetic secrets."""

import importlib.util
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cli = load_script("uvi_downloader")
publication = load_script("check_publication")


class PrivacyTests(unittest.TestCase):
    def test_http_error_does_not_include_url_or_response_body(self):
        url = "https://example.invalid/?private=synthetic-secret"
        client = cli.UVIClient(url)
        error = HTTPError(url, 403, "sensitive reason", {}, io.BytesIO(b"private response"))
        with patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(cli.UVIError) as raised:
                client._request(url, method="GET")
        self.assertEqual(str(raised.exception), "Portal request failed with HTTP 403.")
        self.assertTrue(raised.exception.__suppress_context__)

    def test_network_error_does_not_include_sensitive_reason(self):
        client = cli.UVIClient("https://example.invalid/")
        with patch.object(client.opener, "open", side_effect=URLError("synthetic-secret")):
            with self.assertRaises(cli.UVIError) as raised:
                client._request(client.launch_url, method="GET")
        self.assertEqual(str(raised.exception), "Could not reach the portal.")

    def test_invalid_protocol_does_not_echo_response(self):
        with self.assertRaises(cli.UVIError) as raised:
            cli.parse_om("private response with synthetic-secret")
        self.assertNotIn("synthetic-secret", str(raised.exception))

    def test_request_summary_excludes_escaped_password(self):
        body = r'event _om 3{}{{ConfigureEvent 0{{value "test\"secret"}}}{ActionEvent 0{}}}'
        self.assertEqual(cli.summarize_request_body(body),
                         "configure_events=1 action_events=1 function_events=0")

    def test_publication_check_rejects_personal_email_without_echoing_it(self):
        address = "resident" + "@" + "private.test"
        findings = publication.inspect_content("README.md", address.encode())
        self.assertTrue(findings)
        self.assertTrue(all(address not in finding for finding in findings))

    def test_publication_check_rejects_launch_token(self):
        content = ("--launch-token '" + "A" * 64 + "'").encode()
        self.assertTrue(publication.inspect_content("README.md", content))

    def test_publication_check_rejects_capture_even_if_empty(self):
        self.assertTrue(publication.inspect_file("trace/capture.har", "trace/capture.har", b"{}"))

    def test_publication_check_allows_documented_placeholders(self):
        content = b"--launch-token 'LAUNCH_TOKEN' --login-email 'name@example.invalid'"
        self.assertFalse(publication.inspect_content("README.md", content))

    def test_publication_check_finds_private_data_in_history_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args, data=None):
                return subprocess.check_output(["git", "-C", str(root), *args], input=data,
                                               stderr=subprocess.DEVNULL)

            git("init", "-b", "main")
            git("config", "user.name", "Example")
            git("config", "user.email", "example@example.invalid")
            document = root / "README.md"
            document.write_text("--launch-token '" + "A" * 64 + "'\n")
            git("add", "README.md")
            git("-c", "commit.gpgsign=false", "commit", "-m", "Synthetic private example")
            document.write_text("Safe current content\n")
            git("add", "README.md")
            git("-c", "commit.gpgsign=false", "commit", "-m", "Remove private example")
            capture = root / "synthetic.har"
            capture.write_text("{}")
            git("add", "synthetic.har")
            tree = git("write-tree").decode().strip()
            git("update-ref", "refs/test/private-snapshot", tree)
            git("reset", "--hard", "HEAD")
            output = io.StringIO()
            with patch.object(publication, "ROOT", root), patch.object(sys, "argv", ["check", "--history"]), redirect_stdout(output):
                self.assertEqual(publication.main(), 1)
            self.assertIn("literal launch token", output.getvalue())
            self.assertIn("refs/test/private-snapshot:synthetic.har", output.getvalue())
            self.assertNotIn("A" * 64, output.getvalue())


if __name__ == "__main__":
    unittest.main()
