"""Tokenless status must preserve failed local checks, without runtime access.

All input/output paths, including the legacy fixed RESULT.md and public mirror
paths, are redirected to temporary fixtures. Marker equality is not crypto.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHASKA_DATA_DIR", tempfile.mkdtemp(prefix="chaska-proof-import-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402

LOOP_PROJECT = api.LOOP_SB.parent
PUBLIC_PROVE = Path("/opt/alloyscape/forge/public/ztfi/TRIBE-PROVE-LATEST.json")


class TokenlessProveTest(unittest.TestCase):
  def setUp(self) -> None:
    temporary = tempfile.TemporaryDirectory(prefix="chaska-proof-")
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.project = self.root / "loop"
    self.project.mkdir()
    self.coverage = self.root / "SEAT-COVERAGE.json"
    self.scoreboard = self.project / "scoreboard.json"
    self.result = self.project / "RESULT.md"
    self.qich = self.root / "qiwicha_manifest.qich"
    self.router = self.root / "router.md"
    self.prove = self.root / "TRIBE-PROVE-LATEST.json"
    self.public = self.root / "public" / "TRIBE-PROVE-LATEST.json"
    self.valid_coverage = {
      "think_seats": [f"seat-{n}" for n in range(110)],
      "living_wire_on_disk": {"count": 111},
      "wired_after": 111,
      "whole_tribe": True,
      "signatures": {name: api.SIGS[name] for name in ("ztfi_p3", "ztfi_p4", "anchor", "qde")},
      "stamp": "synthetic-fixture-only",
    }
    self.coverage.write_text(json.dumps(self.valid_coverage))
    self.scoreboard.write_text(json.dumps({"passed": 24, "loops": 24}))
    self.qich.write_text("{}")
    self.router.write_text("Synthetic router fixture, not a runtime observation.\n")

    def isolated_path(path):
      # Never fall back to a real runtime path, even on the buggy baseline.
      if path == str(LOOP_PROJECT):
        return self.project
      if path == str(PUBLIC_PROVE):
        return self.public
      raise AssertionError(f"unexpected runtime path: {path!r}")

    for patcher in (
      mock.patch.object(api, "COVERAGE", self.coverage),
      mock.patch.object(api, "LOOP_SB", self.scoreboard),
      mock.patch.object(api, "QICH", self.qich),
      mock.patch.object(api, "ROUTER", self.router),
      mock.patch.object(api, "PROVE", self.prove),
      mock.patch.object(api, "Path", side_effect=isolated_path),
      mock.patch.object(api, "whisper", side_effect=AssertionError("no LLM expected")),
      mock.patch.object(api.subprocess, "run", side_effect=AssertionError("no process expected")),
    ):
      patcher.start()
      self.addCleanup(patcher.stop)

  def observe(self):
    body = api.tokenless_prove()
    # A false returned verdict must remain false in both written status copies.
    self.assertEqual(json.loads(self.prove.read_text()), body)
    self.assertEqual(json.loads(self.public.read_text()), body)
    return body

  def test_valid_24_of_24_keeps_existing_success_contract(self):
    body = self.observe()
    self.assertIs(body["ok"], True)
    self.assertTrue(all(body["checks"].values()))
    self.assertEqual(body["mode"], "tokenless_no_llm")
    self.assertEqual(body["coverage"]["think_seats"], 110)
    self.assertEqual(body["loop"]["scoreboard"], {"passed": 24, "loops": 24})

  def test_explicit_legacy_ok_remains_reported_success(self):
    self.scoreboard.write_text(json.dumps({"ok": True}))
    body = self.observe()
    self.assertIs(body["ok"], True)
    self.assertIs(body["checks"]["loop_24_24"], True)
    self.assertEqual(body["loop"]["scoreboard"], {"ok": True})

  def test_bad_or_missing_p3_alone_cannot_report_success(self):
    for value in (None, "wrong-marker", "", 0):
      coverage = json.loads(json.dumps(self.valid_coverage))
      coverage["signatures"]["ztfi_p3"] = value
      self.coverage.write_text(json.dumps(coverage))
      with self.subTest(marker=value):
        body = self.observe()
        self.assertIs(body["checks"]["p3_sig"], False)
        self.assertIs(body["ok"], False)
        self.assertTrue(all(v for k, v in body["checks"].items() if k != "p3_sig"))
    del coverage["signatures"]["ztfi_p3"]
    self.coverage.write_text(json.dumps(coverage))
    body = self.observe()
    self.assertIs(body["checks"]["p3_sig"], False)
    self.assertIs(body["ok"], False)

  def test_result_file_cannot_promote_failed_or_malformed_counters(self):
    self.result.write_text("Arbitrary text: this file is not a passing scoreboard.\n")
    for scoreboard in (
      {"passed": 23, "loops": 24},
      {"passed": 24, "loops": 25},
      {"passed": "24", "loops": "24"},
      {"passed": None, "loops": 24},
      {"ok": False},
      {"ok": "true"},
      {},
    ):
      self.scoreboard.write_text(json.dumps(scoreboard))
      with self.subTest(scoreboard=scoreboard):
        body = self.observe()
        self.assertIs(body["checks"]["loop_24_24"], False)
        self.assertIs(body["ok"], False)
        self.assertTrue(all(v for k, v in body["checks"].items() if k != "loop_24_24"))

  def test_failure_without_result_file_stays_failed(self):
    self.scoreboard.write_text(json.dumps({"passed": 0, "loops": 24, "ok": False}))
    body = self.observe()
    self.assertIs(body["checks"]["loop_24_24"], False)
    self.assertIs(body["ok"], False)

  def test_missing_scoreboard_is_not_rescued_by_result_file(self):
    self.scoreboard.unlink()
    self.result.write_text("No scoreboard is present.\n")
    body = self.observe()
    self.assertIs(body["checks"]["loop_scoreboard"], False)
    self.assertIs(body["checks"]["loop_24_24"], False)
    self.assertIs(body["ok"], False)

  def test_other_marker_checks_remain_required(self):
    for marker, check in (("ztfi_p4", "p4_sig"), ("anchor", "anchor_sig"), ("qde", "qde_sig")):
      coverage = json.loads(json.dumps(self.valid_coverage))
      coverage["signatures"][marker] = "wrong-marker"
      self.coverage.write_text(json.dumps(coverage))
      with self.subTest(marker=marker):
        body = self.observe()
        self.assertIs(body["checks"][check], False)
        self.assertIs(body["ok"], False)

  def test_required_presence_checks_remain_required(self):
    for path, check in ((self.qich, "qiwicha_manifest"), (self.router, "router_doc")):
      content = path.read_text()
      path.unlink()
      with self.subTest(check=check):
        body = self.observe()
        self.assertIs(body["checks"][check], False)
        self.assertIs(body["ok"], False)
      path.write_text(content)


if __name__ == "__main__":
  unittest.main()
