"""Upload storage keeps caller filenames out of filesystem paths.

Run: python3 -m unittest discover -s tests -v
Regressions for direct commit 6597727 (CodeQL py/path-injection in save_upload):
the payload is stored under the server-generated id and the caller's sanitised
filename is metadata only; records keep the configured CHASKA_DATA_DIR path; an
entry that already exists at the storage path is never followed or overwritten.
No model, llama.cpp binary or network is needed.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
import unittest.mock as mock

os.environ.setdefault("CHASKA_DATA_DIR", tempfile.mkdtemp(prefix="chaska-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402

HOSTILE_NAMES = (
  "../../etc/passwd",
  "..",
  "/etc/shadow",
  "a/../../b.txt",
  "..\\..\\windows\\win.ini",
  "nul\x00byte.txt",
  "ünïcode name.txt",
  "x" * 400 + ".txt",
  "",
)


class _UploadDirMixin:
  def use_upload_dir(self, upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    for patcher in (
      mock.patch.object(api, "UPLOAD_DIR", upload_dir),
      mock.patch.object(api, "UPLOAD_META", upload_dir / "index.json"),
    ):
      patcher.start()
      self.addCleanup(patcher.stop)


class UploadStorageTest(_UploadDirMixin, unittest.TestCase):
  def setUp(self) -> None:
    temporary = tempfile.TemporaryDirectory(prefix="chaska-upload-")
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.use_upload_dir(self.root / "data" / "uploads")

  def test_caller_filename_never_forms_part_of_the_storage_path(self) -> None:
    ids = []
    for name in HOSTILE_NAMES:
      with self.subTest(name=name):
        out = api.save_upload(name, b"payload", media_type="text/plain")
        self.assertTrue(out["ok"], out)
        self.assertRegex(out["id"], r"\A[0-9a-f]{24}\Z")
        rec = api.get_upload(out["id"])
        stored = Path(rec["path"])
        self.assertEqual(stored, api.UPLOAD_DIR / out["id"])
        self.assertEqual(stored.read_bytes(), b"payload")
        # The sanitised display name keeps its existing contract.
        self.assertRegex(out["filename"], r"\A[A-Za-z0-9._-]{1,120}\Z")
        self.assertEqual(rec["filename"], out["filename"])
        ids.append(out["id"])
    created = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*")}
    expected = {"data", "data/uploads", "data/uploads/index.json"}
    expected |= {f"data/uploads/{fid}" for fid in ids}
    self.assertEqual(created, expected)

  def test_records_keep_the_configured_data_dir_path_across_a_storage_move(self) -> None:
    disk1, disk2 = self.root / "disk1", self.root / "disk2"
    (disk1 / "uploads").mkdir(parents=True)
    data = self.root / "chaska-data"  # the configured CHASKA_DATA_DIR is a symlink
    data.symlink_to(disk1, target_is_directory=True)
    self.use_upload_dir(data / "uploads")
    out = api.save_upload("notes.txt", b"hello", media_type="text/plain")
    self.assertTrue(out["ok"], out)
    # An operator moves the data volume and re-points the configured symlink.
    disk1.rename(disk2)
    data.unlink()
    data.symlink_to(disk2, target_is_directory=True)
    rec = api.get_upload(out["id"])
    self.assertIsNotNone(rec)
    self.assertTrue(Path(rec["path"]).is_file(), rec["path"])
    self.assertEqual(Path(rec["path"]).read_bytes(), b"hello")

  def test_an_existing_entry_at_the_storage_path_is_never_written_through(self) -> None:
    fid = "ab" * 12
    outside = self.root / "outside.txt"
    outside.write_bytes(b"original")
    (api.UPLOAD_DIR / fid).symlink_to(outside)
    with mock.patch.object(api.secrets, "token_hex", return_value=fid):
      out = api.save_upload("x.txt", b"attacker", media_type="text/plain")
    self.assertEqual(out, {"ok": False, "error": "upload_conflict"})
    self.assertEqual(outside.read_bytes(), b"original")
    self.assertIsNone(api.get_upload(fid))

  def test_an_id_collision_never_overwrites_an_earlier_upload(self) -> None:
    fid = "cd" * 12
    with mock.patch.object(api.secrets, "token_hex", return_value=fid):
      first = api.save_upload("a.txt", b"first", media_type="text/plain")
      second = api.save_upload("a.txt", b"second", media_type="text/plain")
    self.assertTrue(first["ok"], first)
    self.assertEqual(second, {"ok": False, "error": "upload_conflict"})
    rec = api.get_upload(fid)
    self.assertEqual(Path(rec["path"]).read_bytes(), b"first")

class UploadHttpTest(_UploadDirMixin, unittest.TestCase):
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
    temporary = tempfile.TemporaryDirectory(prefix="chaska-upload-http-")
    self.addCleanup(temporary.cleanup)
    self.use_upload_dir(Path(temporary.name) / "uploads")

  def request(self, method: str, path: str, body: bytes | None = None, ctype: str = "text/plain"):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
    conn.request(method, path, body=body, headers={"Content-Type": ctype} if body is not None else {})
    resp = conn.getresponse()
    out = (resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read())
    conn.close()
    return out

  def test_hostile_upload_name_round_trips_as_metadata_only(self) -> None:
    name = urllib.parse.quote("../../etc/passwd", safe="")
    status, _, body = self.request("POST", f"/v1/upload?name={name}", body=b"data")
    self.assertEqual(status, 200, body)
    up = json.loads(body)
    self.assertEqual(up["filename"], ".._.._etc_passwd")
    status, headers, data = self.request("GET", up["url"])
    self.assertEqual((status, data), (200, b"data"))
    self.assertEqual(headers["content-disposition"], 'inline; filename=".._.._etc_passwd"')
    self.assertEqual(sorted(p.name for p in api.UPLOAD_DIR.iterdir()), sorted([up["id"], "index.json"]))


if __name__ == "__main__":
  unittest.main()
