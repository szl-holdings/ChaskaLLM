"""Prompt bytes stay outside argv; only isolated local fixture processes run."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


class PromptTransportTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory(prefix="chaska-transport-test-")
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    with mock.patch.dict(os.environ, {"CHASKA_DATA_DIR": str(self.root / "data")}):
      spec = importlib.util.spec_from_file_location(
        "chaska_prompt_transport", Path(__file__).resolve().parents[1] / "ops/chaskallm_api.py"
      )
      self.api = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(self.api)
    self.cli = self.root / "fixture-cli"
    self.records = self.root / "records"
    self.records.mkdir()
    # This fixture implements only argv/file observation, not llama.cpp parsing or inference.
    self.cli.write_text(
      f"#!{sys.executable}\n"
      "import json, pathlib, stat, sys\n"
      "args = sys.argv[1:]\n"
      "assert '-p' not in args and '--prompt' not in args\n"
      "path = pathlib.Path(args[args.index('--binary-file') + 1])\n"
      "record = {'argv': args, 'path': str(path), 'data': path.read_bytes().hex(), "
      "'file_mode': stat.S_IMODE(path.stat().st_mode), "
      "'dir_mode': stat.S_IMODE(path.parent.stat().st_mode)}\n"
      f"(pathlib.Path({str(self.records)!r}) / (path.parent.name + '.json')).write_text(json.dumps(record))\n"
      "print('Assistant: fixture response')\n"
    )
    self.cli.chmod(0o700)
    self.api.CLI = self.cli
    for key in self.api.MODELS:
      model = self.root / (key + ".gguf")
      model.write_bytes(b"fixture only: no model")
      self.api.MODELS[key] = model
    self.api.GEN_SLOTS = threading.BoundedSemaphore(2)

  def records_read(self):
    return [json.loads(p.read_text()) for p in self.records.glob("*.json")]

  def assert_removed(self, record):
    self.assertFalse(Path(record["path"]).exists())
    self.assertFalse(Path(record["path"]).parent.exists())

  def test_adversarial_unicode_and_newline_prompts_are_exact_file_bytes(self):
    payloads = ["--model /tmp/other.gguf", "-hf hostile/model", "@/etc/passwd",
                "$(touch /tmp/never); & | >", "line one\nline two\n\n",
                "quote \" slash \\ literal \\n", "Hola, κόσμε 🌎", "embedded\x00zero"]
    for prompt in payloads:
      with self.subTest(prompt=repr(prompt)):
        self.assertTrue(self.api.whisper(prompt, model_key="4b")["ok"])
        records = self.records_read()
        record = next(r for r in records if bytes.fromhex(r["data"]) == prompt.encode("utf-8"))
        self.assertNotIn(prompt, record["argv"])
        self.assertEqual(record["file_mode"], 0o600)
        self.assertEqual(record["dir_mode"], 0o700)
        self.assert_removed(record)
    self.assertEqual(len(self.records_read()), len(payloads))

  def test_every_lane_keeps_existing_model_flags_and_prompt_format(self):
    for key in self.api.MODELS:
      with self.subTest(key=key):
        self.assertTrue(self.api.whisper("hello\n", n_predict=19, model_key=key)["ok"])
    records = self.records_read()
    self.assertEqual(len(records), len(self.api.MODELS))
    for record in records:
      args = record["argv"]
      key = Path(args[args.index("-m") + 1]).stem
      expected = b"User: hello\n\nAssistant:" if key in ("tiny", "1.1b") else b"hello\n"
      self.assertEqual(bytes.fromhex(record["data"]), expected)
      self.assertEqual(args[args.index("-n") + 1], "19")
      self.assertEqual(args[args.index("-ngl") + 1], "0")
      self.assertEqual("--jinja" in args, key not in ("tiny", "1.1b"))
      self.assertEqual("-sys" in args, key not in ("tiny", "1.1b"))
      self.assert_removed(record)

  def test_concurrent_calls_have_distinct_files_and_no_prompt_crossover(self):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
      results = list(pool.map(lambda p: self.api.whisper(p, model_key="4b"), ["first", "second"]))
    self.assertTrue(all(r["ok"] for r in results))
    records = self.records_read()
    self.assertEqual({bytes.fromhex(r["data"]) for r in records}, {b"first", b"second"})
    self.assertEqual(len({r["path"] for r in records}), 2)
    for record in records:
      self.assert_removed(record)

  def test_busy_call_creates_no_file_and_starts_no_process(self):
    self.api.GEN_SLOTS = threading.BoundedSemaphore(1)
    self.api.GEN_SLOTS.acquire()
    self.api.GEN_WAIT_S = 0
    with mock.patch.object(self.api.subprocess, "run") as run, \
         mock.patch.object(self.api.tempfile, "TemporaryDirectory") as directory:
      out = self.api.whisper("secret prompt", model_key="4b")
    self.assertEqual(out["error"], "busy")
    run.assert_not_called()
    directory.assert_not_called()

  def test_timeout_and_spawn_failure_remove_prompt_and_release_slot(self):
    for error, expected in [(subprocess.TimeoutExpired("fixture", 1), "timeout"),
                            (OSError("sensitive local path"), "generation_io_error")]:
      with self.subTest(error=type(error).__name__):
        self.api.GEN_SLOTS = threading.BoundedSemaphore(1)
        paths = []
        def fail(args, **kwargs):
          path = Path(args[args.index("--binary-file") + 1])
          self.assertEqual(path.read_bytes(), b"secret prompt")
          self.assertIs(kwargs.get("shell"), False)
          paths.append(path)
          raise error
        with mock.patch.object(self.api.subprocess, "run", side_effect=fail):
          out = self.api.whisper("secret prompt", model_key="4b")
        self.assertEqual(out["error"], expected)
        self.assertNotIn("sensitive", json.dumps(out))
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].parent.exists())
        self.assertTrue(self.api.GEN_SLOTS.acquire(blocking=False))

  def test_temp_storage_failure_releases_slot_without_process(self):
    self.api.GEN_SLOTS = threading.BoundedSemaphore(1)
    with mock.patch.object(self.api.tempfile, "TemporaryDirectory", side_effect=OSError("disk")), \
         mock.patch.object(self.api.subprocess, "run") as run:
      out = self.api.whisper("secret", model_key="4b")
    self.assertEqual(out["error"], "generation_io_error")
    run.assert_not_called()
    self.assertTrue(self.api.GEN_SLOTS.acquire(blocking=False))

  def test_invalid_unicode_never_starts_process_or_writes_prompt(self):
    with mock.patch.object(self.api.subprocess, "run") as run:
      out = self.api.whisper("\ud800", model_key="4b")
    self.assertEqual(out["error"], "invalid_prompt_encoding")
    run.assert_not_called()
    self.assertEqual(self.records_read(), [])


if __name__ == "__main__":
  unittest.main()
