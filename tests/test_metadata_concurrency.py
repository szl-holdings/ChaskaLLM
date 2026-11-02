"""Offline metadata transactions under concurrent server request interleavings."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock


class MetadataConcurrencyTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.import_root = tempfile.TemporaryDirectory(prefix="chaska-metadata-import-")
    source = Path(__file__).resolve().parents[1] / "ops" / "chaskallm_api.py"
    spec = importlib.util.spec_from_file_location("chaska_metadata_test_api", source)
    cls.api = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"CHASKA_DATA_DIR": cls.import_root.name}):
      spec.loader.exec_module(cls.api)

  @classmethod
  def tearDownClass(cls):
    cls.import_root.cleanup()

  def setUp(self):
    temporary = tempfile.TemporaryDirectory(prefix="chaska-metadata-")
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.uploads = self.root / "uploads"
    self.uploads.mkdir()
    for name, value in {
      "UPLOAD_DIR": self.uploads,
      "UPLOAD_META": self.uploads / "index.json",
      "KEYS_PATH": self.root / "api-keys.json",
    }.items():
      patch = mock.patch.object(self.api, name, value)
      patch.start()
      self.addCleanup(patch.stop)

  def overlap_after_first_read(self, loader_name, first, second):
    """Hold request one after its read, then admit request two at a barrier.

    Without a transaction lock, request two can read and finish before request
    one resumes, deterministically exposing a stale snapshot overwrite. With a
    lock, request two cannot enter the loader until request one has committed.
    The wait is bounded in either case; no provider or model is called.
    """
    original = getattr(self.api, loader_name)
    first_read = threading.Event()
    second_read = threading.Event()
    release_first = threading.Event()
    second_started = threading.Barrier(2)
    reads_lock = threading.Lock()
    reads = 0

    def controlled_read():
      nonlocal reads
      value = original()
      with reads_lock:
        reads += 1
        index = reads
      if index == 1:
        first_read.set()
        if not release_first.wait(5):
          raise AssertionError("first metadata request was never released")
      else:
        second_read.set()
      return value

    def enter_second():
      second_started.wait(timeout=5)
      return second()

    with mock.patch.object(self.api, loader_name, side_effect=controlled_read):
      with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first)
        try:
          self.assertTrue(first_read.wait(5), "first request never loaded metadata")
          two = pool.submit(enter_second)
          second_started.wait(timeout=5)
          if second_read.wait(0.2):
            # Complete the racing second write before the stale first one.
            two.result(timeout=5)
        finally:
          release_first.set()
        return one.result(timeout=5), two.result(timeout=5)

  def test_concurrent_upload_successes_all_remain_retrievable(self):
    one, two = self.overlap_after_first_read(
      "_load_uploads",
      lambda: self.api.save_upload("first.txt", b"first", "text/plain"),
      lambda: self.api.save_upload("second.txt", b"second", "text/plain"),
    )
    self.assertTrue(one["ok"] and two["ok"])
    self.assertNotEqual(one["id"], two["id"])
    for response, payload in [(one, b"first"), (two, b"second")]:
      record = self.api.get_upload(response["id"])
      self.assertIsNotNone(record, "successful upload was lost from the metadata index")
      self.assertEqual(Path(record["path"]).read_bytes(), payload)

  def test_concurrent_mints_both_keys_remain_valid(self):
    one, two = self.overlap_after_first_read(
      "_load_keys",
      lambda: self.api.mint_api_key("first"),
      lambda: self.api.mint_api_key("second"),
    )
    for response in (one, two):
      verified = self.api.verify_api_key(response["key"])
      self.assertTrue(verified["ok"], "successful key mint was lost from the key store")
      self.assertEqual(verified["id"], response["id"])

  def test_concurrent_key_use_preserves_every_call(self):
    minted = self.api.mint_api_key("counter")
    one, two = self.overlap_after_first_read(
      "_load_keys",
      lambda: self.api.verify_api_key(minted["key"]),
      lambda: self.api.verify_api_key(minted["key"]),
    )
    self.assertTrue(one["ok"] and two["ok"])
    record = next(r for r in self.api._load_keys()["keys"] if r["id"] == minted["id"])
    self.assertEqual(record["calls"], 2)

  def test_key_use_cannot_overwrite_concurrent_mint(self):
    existing = self.api.mint_api_key("existing")
    used, minted = self.overlap_after_first_read(
      "_load_keys",
      lambda: self.api.verify_api_key(existing["key"]),
      lambda: self.api.mint_api_key("new"),
    )
    self.assertTrue(used["ok"] and minted["ok"])
    self.assertTrue(self.api.verify_api_key(minted["key"])["ok"])
    records = {r["id"]: r for r in self.api._load_keys()["keys"]}
    self.assertEqual(records[existing["id"]]["calls"], 1)
    self.assertEqual(set(records), {existing["id"], minted["id"]})

  def test_failed_replace_preserves_previous_snapshot_and_removes_temp_file(self):
    self.api.mint_api_key("existing")
    before = self.api.KEYS_PATH.read_bytes()
    with mock.patch.object(self.api.os, "replace", side_effect=OSError("replace failed")):
      with self.assertRaises(OSError):
        self.api.mint_api_key("must not report success")
    self.assertEqual(self.api.KEYS_PATH.read_bytes(), before)
    self.assertEqual(list(self.root.glob(".api-keys.json.*.tmp")), [])

  def test_failed_file_sync_does_not_publish_or_report_new_key(self):
    self.api.mint_api_key("existing")
    before = self.api.KEYS_PATH.read_bytes()
    with mock.patch.object(self.api.os, "fsync", side_effect=OSError("sync failed")):
      with self.assertRaises(OSError):
        self.api.mint_api_key("must not report success")
    self.assertEqual(self.api.KEYS_PATH.read_bytes(), before)
    self.assertEqual(list(self.root.glob(".api-keys.json.*.tmp")), [])

  def test_absent_stores_initialize_and_supported_records_round_trip(self):
    self.assertEqual(self.api._load_uploads(), {"version": 1, "files": {}})
    self.assertEqual(self.api._load_keys(), {"version": 1, "keys": []})
    upload = self.api.save_upload("first.txt", b"first", "text/plain")
    key = self.api.mint_api_key("first")
    self.assertEqual(self.api.get_upload(upload["id"])["bytes"], 5)
    self.assertTrue(self.api.verify_api_key(key["key"])["ok"])

  def test_corrupt_or_unsupported_stores_are_preserved_before_mutation(self):
    common = [
      b"", b"{truncated", b"\xff", b"[]", b"null", b"{}",
      b'{"version":true}', b'{"version":2}',
      b'{"version":1,"version":1}',
      b'{"version":1,"extra":NaN}', b'{"version":1,"extra":1e999}',
    ]
    stores = [
      (self.api.UPLOAD_META, self.api._load_uploads,
       lambda: self.api.save_upload("new.txt", b"new", "text/plain"),
       [b'{"version":1,"files":[]}', b'{"version":1,"files":{"id":{}}}',
        b'{"version":1,"files":{},"files":{}}']),
      (self.api.KEYS_PATH, self.api._load_keys, lambda: self.api.mint_api_key("new"),
       [b'{"version":1,"keys":{}}', b'{"version":1,"keys":[{}]}',
        b'{"version":1,"keys":[],"keys":[]}']),
    ]
    for path, loader, mutate, malformed in stores:
      for raw in common + malformed:
        with self.subTest(store=path.name, case=raw[:24]):
          path.write_bytes(raw)
          payloads = set(self.uploads.glob("*__*"))
          with self.assertRaises(self.api.MetadataStoreError):
            loader()
          with self.assertRaises(self.api.MetadataStoreError):
            mutate()
          self.assertEqual(path.read_bytes(), raw)
          self.assertEqual(set(self.uploads.glob("*__*")), payloads)

  def test_corrupt_key_store_blocks_verification_without_replacing_evidence(self):
    raw = b'{"version":1,"keys":[{"active":true}]}'
    self.api.KEYS_PATH.write_bytes(raw)
    with self.assertRaises(self.api.MetadataStoreError):
      self.api.verify_api_key("chaska_synthetic_test_value")
    self.assertEqual(self.api.KEYS_PATH.read_bytes(), raw)

  def test_invalid_record_identity_or_types_do_not_accept_successful_mutations(self):
    upload = self.api.save_upload("existing.txt", b"existing", "text/plain")
    key = self.api.mint_api_key("existing")
    uploads = self.api._load_uploads()
    keys = self.api._load_keys()
    cases = []
    for field, value in [("id", "different"), ("bytes", True), ("path", None), ("kind", [])]:
      candidate = json.loads(json.dumps(uploads))
      candidate["files"][upload["id"]][field] = value
      cases.append((self.api.UPLOAD_META, candidate, lambda: self.api.save_upload("new", b"new")))
    for field, value in [("sha256", "not-a-digest"), ("calls", True), ("active", 1), ("last_used", {})]:
      candidate = json.loads(json.dumps(keys))
      candidate["keys"][0][field] = value
      cases.append((self.api.KEYS_PATH, candidate, lambda: self.api.verify_api_key(key["key"])))
    duplicate = json.loads(json.dumps(keys))
    duplicate["keys"].append(duplicate["keys"][0].copy())
    cases.append((self.api.KEYS_PATH, duplicate, lambda: self.api.mint_api_key("new")))
    for path, candidate, mutate in cases:
      with self.subTest(store=path.name, candidate=candidate):
        raw = json.dumps(candidate).encode()
        path.write_bytes(raw)
        with self.assertRaises(self.api.MetadataStoreError):
          mutate()
        self.assertEqual(path.read_bytes(), raw)

  def test_existing_unreadable_store_is_not_treated_as_absent(self):
    self.api.KEYS_PATH.mkdir()
    with self.assertRaises(self.api.MetadataStoreError):
      self.api.mint_api_key("new")
    self.assertTrue(self.api.KEYS_PATH.is_dir())
    with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
      with self.assertRaises(self.api.MetadataStoreError):
        self.api._load_uploads()

  def test_corrupt_metadata_returns_unavailable_from_http_reads_and_writes(self):
    self.api.KEYS_PATH.write_bytes(b"corrupt key metadata")
    self.api.UPLOAD_META.write_bytes(b"corrupt upload metadata")
    server = self.api.ThreadingHTTPServer(("127.0.0.1", 0), self.api.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
      for method, path, body in [("POST", "/v1/keys", b"{}"),
                                  ("POST", "/v1/upload?name=new.txt", b"new"),
                                  ("GET", "/v1/files/unknown", None)]:
        with self.subTest(method=method, path=path):
          connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
          try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.read()),
                             {"ok": False, "error": "metadata_store_unavailable"})
          finally:
            connection.close()
    finally:
      server.shutdown()
      server.server_close()
      worker.join(timeout=5)
    self.assertEqual(self.api.KEYS_PATH.read_bytes(), b"corrupt key metadata")
    self.assertEqual(self.api.UPLOAD_META.read_bytes(), b"corrupt upload metadata")


if __name__ == "__main__":
  unittest.main()
