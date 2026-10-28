"""/v1/info must name the model actually being served and its real license.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHASKA_DATA_DIR", tempfile.mkdtemp(prefix="chaska-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402


class ModelInfoTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.server = api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
    cls.port = cls.server.server_address[1]
    threading.Thread(target=cls.server.serve_forever, daemon=True).start()

  @classmethod
  def tearDownClass(cls) -> None:
    cls.server.shutdown()
    cls.server.server_close()

  def setUp(self) -> None:
    self.dir = Path(tempfile.mkdtemp(prefix="chaska-models-"))

  def models(self, *present: str) -> dict:
    """A MODELS map in a temp dir where only the named lanes have a GGUF on disk."""
    files = {k: self.dir / p.name for k, p in api.MODELS.items()}
    for key in present:
      files[key].write_bytes(b"gguf")
    return files

  def info(self) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
    conn.request("GET", "/v1/info")
    body = json.loads(conn.getresponse().read())
    conn.close()
    return body

  def test_default_lane_is_the_apache_licensed_4b(self) -> None:
    self.assertEqual(api.DEFAULT_MODEL_KEY, "4b")
    self.assertEqual(api.MODELS["default"], api.MODELS["4b"])
    with mock.patch.dict(api.MODELS, self.models("4b", "3b")):
      self.assertEqual(api.resolve_model()[0], "4b")
      out = self.info()
    self.assertEqual(out["base_model"], "Qwen/Qwen3-4B-Instruct-2507")
    self.assertEqual(out["license"], "apache-2.0")
    self.assertEqual(out["default_model"], "4b")

  def test_fallback_to_legacy_3b_reports_its_research_license(self) -> None:
    with mock.patch.dict(api.MODELS, self.models("3b")):
      self.assertEqual(api.resolve_model()[0], "3b")
      out = self.info()
    self.assertEqual(out["base_model"], "Qwen/Qwen2.5-3B-Instruct")
    self.assertNotEqual(out["license"], "apache-2.0")
    self.assertIn("non-commercial", out["license"])

  def test_unpublished_lane_reports_unknown_rather_than_a_guess(self) -> None:
    with mock.patch.dict(api.MODELS, self.models("1.1b")):
      out = self.info()
    self.assertEqual(out["default_model"], "1.1b")
    self.assertIsNone(out["base_model"])
    self.assertEqual(out["license"], "unknown")

  def test_4b_uses_the_chat_template_path(self) -> None:
    cli = self.dir / "llama-cli"
    cli.write_bytes(b"x")
    with mock.patch.object(api, "CLI", cli), mock.patch.dict(api.MODELS, self.models("4b")), \
        mock.patch.object(api.subprocess, "run") as run:
      run.return_value = mock.Mock(returncode=0, stdout="hello", stderr="")
      out = api.whisper("hi", model_key="4b")
    cmd = run.call_args.args[0]
    self.assertEqual(out["model_key"], "4b")
    self.assertIn("--jinja", cmd)
    self.assertIn("-sys", cmd)
    self.assertEqual(cmd[cmd.index("-t") + 1], "12")


if __name__ == "__main__":
  unittest.main()
