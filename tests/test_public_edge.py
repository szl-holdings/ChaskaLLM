"""Regression tests for the ChaskaLLM public-edge bounds.

Run: python3 -m unittest discover -s tests -v
No model, llama.cpp binary, NVIDIA key or network is needed: generation and the
image bridge are replaced with fakes, and data files go to a temp directory.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
import unittest.mock as mock

_TMP = tempfile.mkdtemp(prefix="chaska-test-")
os.environ["CHASKA_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402

REAL_WHISPER = api.whisper
PUBLIC = {"X-Real-IP": "203.0.113.7"}


class _FakeNvidiaResponse:
  def __init__(self) -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    self._body = json.dumps({"artifacts": [{"base64": base64.b64encode(png).decode()}]}).encode()

  def read(self) -> bytes:
    return self._body

  def __enter__(self):
    return self

  def __exit__(self, *exc) -> None:
    return None


class PublicEdgeTest(unittest.TestCase):
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
    api.RATE = api.RateWindow()
    api.IMAGE_CAP = api.DailyCap(api.IMAGE_DAILY_CAP)
    self.gen_calls: list[dict] = []
    self.nvidia_calls = 0

    def fake_whisper(prompt, n_predict=64, model_key=None):
      self.gen_calls.append({"n_predict": n_predict, "model_key": model_key})
      return {"ok": True, "text": "hi", "model_key": model_key}

    def fake_urlopen(req, timeout=None):
      self.nvidia_calls += 1
      return _FakeNvidiaResponse()

    for patcher in (
      mock.patch.object(api, "whisper", side_effect=fake_whisper),
      mock.patch.object(api, "_nvidia_image_key", return_value=("nvapi-test", "test")),
      mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
      patcher.start()
      self.addCleanup(patcher.stop)

  def post(self, path: str, body: dict | None = None, headers: dict | None = None, raw: bytes | None = None, ctype: str = "application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
    data = raw if raw is not None else json.dumps(body or {}).encode()
    conn.request("POST", path, body=data, headers={"Content-Type": ctype, **(headers or {})})
    resp = conn.getresponse()
    out = (resp.status, json.loads(resp.read() or b"{}"))
    conn.close()
    return out

  def get(self, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers, body

  def test_client_ip_trusts_forwarding_headers_only_from_loopback(self) -> None:
    class H:
      def __init__(self, peer, headers):
        self.client_address = (peer, 1234)
        self.headers = headers

    self.assertEqual(api.client_ip(H("127.0.0.1", {"X-Real-IP": "198.51.100.4"})), "198.51.100.4")
    self.assertEqual(api.client_ip(H("127.0.0.1", {"X-Forwarded-For": "10.0.0.9, 198.51.100.5"})), "198.51.100.5")
    self.assertEqual(api.client_ip(H("127.0.0.1", {})), "127.0.0.1")
    # A non-loopback peer cannot spoof its address or claim to be local.
    self.assertEqual(api.client_ip(H("198.51.100.6", {"X-Real-IP": "127.0.0.1"})), "198.51.100.6")
    self.assertFalse(api.client_is_local(H("127.0.0.1", {"X-Real-IP": "198.51.100.4"})))

  def test_public_image_calls_are_rate_limited_per_ip(self) -> None:
    for _ in range(api.IMAGE_PER_IP_HOUR):
      status, out = self.post("/v1/images", {"prompt": "a cat"}, PUBLIC)
      self.assertEqual(status, 200, out)
    status, out = self.post("/v1/images", {"prompt": "a cat"}, PUBLIC)
    self.assertEqual((status, out["error"]), (429, "rate_limited"))
    # The chat image path shares the same bucket.
    status, out = self.post("/v1/chat", {"prompt": "draw a cat"}, PUBLIC)
    self.assertEqual(status, 429)
    self.assertEqual(self.nvidia_calls, api.IMAGE_PER_IP_HOUR)

  def test_image_daily_cap_bounds_nvidia_spend_across_callers(self) -> None:
    api.IMAGE_CAP = api.DailyCap(2)
    results = [self.post("/v1/images", {"prompt": "a cat"}, {"X-Real-IP": f"203.0.113.{i}"}) for i in range(4)]
    self.assertEqual([s for s, _ in results], [200, 200, 502, 502])
    self.assertEqual(results[2][1]["error"], "image_daily_cap_reached")
    self.assertEqual(self.nvidia_calls, 2)

  def test_image_size_is_clamped(self) -> None:
    sent = {}

    def capture(req, timeout=None):
      sent.update(json.loads(req.data))
      return _FakeNvidiaResponse()

    with mock.patch("urllib.request.urlopen", side_effect=capture):
      self.post("/v1/images", {"prompt": "a cat", "width": 100000, "height": "tall"}, PUBLIC)
    self.assertEqual((sent["width"], sent["height"]), (api.IMAGE_MAX_SIDE, 1024))

  def test_anonymous_7b_is_refused_and_keyed_7b_allowed(self) -> None:
    seven = Path(_TMP) / "7b.gguf"
    seven.write_bytes(b"x")
    with mock.patch.dict(api.MODELS, {"7b": seven}):
      status, out = self.post("/v1/chat", {"prompt": "hello", "model": "7b"}, PUBLIC)
      self.assertEqual((status, out["error"]), (403, "api_key_required_for_7b"))
      self.assertEqual(self.gen_calls, [])
      _, minted = self.post("/v1/keys", {"label": "test"})
      status, out = self.post("/v1/chat", {"prompt": "hello", "model": "7b"}, {**PUBLIC, "Authorization": f"Bearer {minted['key']}"})
      self.assertEqual(status, 200, out)
      self.assertEqual(self.gen_calls[-1]["model_key"], "7b")

  def test_invalid_key_is_still_rejected(self) -> None:
    status, out = self.post("/v1/chat", {"prompt": "hello"}, {**PUBLIC, "Authorization": "Bearer chaska_wrong"})
    self.assertEqual((status, out["error"]), (401, "invalid_api_key"))

  def test_n_predict_is_clamped(self) -> None:
    self.post("/v1/chat", {"prompt": "hello", "n_predict": 100000}, PUBLIC)
    self.post("/v1/chat", {"prompt": "hello", "max_tokens": "lots"}, PUBLIC)
    self.assertEqual([c["n_predict"] for c in self.gen_calls], [api.MAX_N_PREDICT, 64])

  def test_public_chat_is_rate_limited_but_loopback_is_not(self) -> None:
    with mock.patch.object(api, "CHAT_PER_IP_MINUTE", 2):
      codes = [self.post("/v1/chat", {"prompt": "hello"}, PUBLIC)[0] for _ in range(3)]
      self.assertEqual(codes, [200, 200, 429])
      codes = [self.post("/v1/chat", {"prompt": "hello"})[0] for _ in range(3)]
      self.assertEqual(codes, [200, 200, 200])

  def test_public_key_minting_is_rate_limited(self) -> None:
    codes = [self.post("/v1/keys", {}, PUBLIC)[0] for _ in range(api.KEY_MINT_PER_IP_HOUR + 1)]
    self.assertEqual(codes[-1], 429)
    self.assertTrue(all(c == 200 for c in codes[:-1]))

  def test_oversized_body_is_refused_before_it_is_read(self) -> None:
    with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
      sock.sendall(
        b"POST /v1/chat HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {api.MAX_JSON_BYTES + 1}\r\n\r\n".encode()
        + b"{}"
      )
      head = sock.recv(4096).decode("latin-1")
    self.assertTrue(head.startswith("HTTP/1.0 413") or head.startswith("HTTP/1.1 413"), head)
    self.assertEqual(self.gen_calls, [])

  def test_busy_generation_returns_503(self) -> None:
    with mock.patch.object(api, "whisper", return_value={"ok": False, "error": "busy"}):
      status, out = self.post("/v1/chat", {"prompt": "hello"}, PUBLIC)
    self.assertEqual((status, out["error"]), (503, "busy"))

  def test_generation_slots_bound_concurrency(self) -> None:
    cli = Path(_TMP) / "llama-cli"
    model = Path(_TMP) / "3b.gguf"
    cli.write_bytes(b"x")
    model.write_bytes(b"x")
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    with mock.patch.object(api, "CLI", cli), mock.patch.dict(api.MODELS, {"3b": model}), \
        mock.patch.object(api, "GEN_SLOTS", slots), mock.patch.object(api, "GEN_WAIT_S", 0.05), \
        mock.patch.object(api.subprocess, "run") as run:
      out = REAL_WHISPER("hello", model_key="3b")
      self.assertEqual(out["error"], "busy")
      run.assert_not_called()
      slots.release()
      run.return_value = mock.Mock(returncode=0, stdout="Assistant: hi there", stderr="")
      out = REAL_WHISPER("hello", model_key="3b")
      self.assertTrue(out["ok"], out)
      # The slot is released after the run.
      self.assertTrue(slots.acquire(timeout=0.1))

  def test_uploaded_html_downloads_instead_of_rendering(self) -> None:
    _, up = self.post("/v1/upload?name=x.html", raw=b"<script>alert(1)</script>", ctype="text/html")
    status, headers, _ = self.get(f"/v1/files/{up['id']}")
    self.assertEqual(status, 200)
    self.assertEqual(headers["content-type"], "application/octet-stream")
    self.assertTrue(headers["content-disposition"].startswith("attachment;"))
    self.assertEqual(headers["x-content-type-options"], "nosniff")
    _, up = self.post("/v1/upload?name=x.png", raw=b"\x89PNG\r\n\x1a\n", ctype="image/png")
    status, headers, _ = self.get(f"/v1/files/{up['id']}")
    self.assertEqual(headers["content-type"], "image/png")
    self.assertTrue(headers["content-disposition"].startswith("inline;"))


if __name__ == "__main__":
  unittest.main()
