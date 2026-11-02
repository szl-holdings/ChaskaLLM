"""Tokenless evidence cannot pass on missing signatures or narrative files.

All evidence and output files are isolated in temporary directories. No model,
external service, or deployment evidence is used by these regression fixtures.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHASKA_DATA_DIR", tempfile.mkdtemp(prefix="chaska-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402


class TokenlessProofTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temp = tempfile.TemporaryDirectory(prefix="chaska-proof-")
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.coverage = {
      "think_seats": list(range(110)),
      "living_wire_on_disk": {"count": 111},
      "whole_tribe": True,
      "signatures": {key: api.SIGS[key] for key in ("ztfi_p3", "ztfi_p4", "anchor", "qde")},
    }
    self.loop = {"passed": 24, "loops": 24}
    for name in ("COVERAGE", "LOOP_SB", "QICH", "ROUTER", "PROVE"):
      patcher = mock.patch.object(api, name, self.root / (name + ".json"))
      patcher.start()
      self.addCleanup(patcher.stop)
    api.QICH.write_text("{}")
    api.ROUTER.write_text("fixture router")

    def isolated_path(value):
      # Redirect the two fixed publication/narrative paths used by the original
      # implementation, so even the failing-baseline run stays inside this fixture.
      if str(value).endswith("wo-recursive-spacetime-loop-20261024T235435Z"):
        return self.root
      if str(value).endswith("/public/ztfi/TRIBE-PROVE-LATEST.json"):
        return self.root / "public" / "proof.json"
      raise AssertionError(f"unexpected fixed path: {value}")

    patcher = mock.patch.object(api, "Path", side_effect=isolated_path)
    patcher.start()
    self.addCleanup(patcher.stop)

  def prove(self):
    api.COVERAGE.write_text(json.dumps(self.coverage))
    api.LOOP_SB.write_text(json.dumps(self.loop))
    result = api.tokenless_prove()
    self.assertEqual(json.loads(api.PROVE.read_text()), result)
    self.assertEqual(json.loads((self.root / "public" / "proof.json").read_text()), result)
    return result

  def test_matching_signature_and_complete_loop_can_pass(self):
    for marker in (None, True):
      with self.subTest(ok=marker):
        if marker is not None:
          self.loop["ok"] = marker
        self.assertTrue(self.prove()["ok"])

  def test_missing_or_mismatched_p3_signature_cannot_pass(self):
    for value in (None, "different-signature"):
      with self.subTest(signature=value):
        if value is None:
          self.coverage["signatures"].pop("ztfi_p3", None)
        else:
          self.coverage["signatures"]["ztfi_p3"] = value
        out = self.prove()
        self.assertFalse(out["checks"]["p3_sig"])
        self.assertFalse(out["ok"])

  def test_result_document_cannot_override_failed_loop(self):
    self.loop = {"passed": 23, "loops": 24, "ok": False}
    (self.root / "RESULT.md").write_text("PASS — narrative is not a scoreboard")
    out = self.prove()
    self.assertFalse(out["checks"]["loop_24_24"])
    self.assertFalse(out["ok"])

  def test_ok_flag_does_not_replace_or_override_loop_counts(self):
    for counts in ({}, {"passed": 23, "loops": 24}, {"passed": 24, "loops": 25}):
      with self.subTest(counts=counts):
        self.loop = {**counts, "ok": True}
        out = self.prove()
        self.assertFalse(out["checks"]["loop_24_24"])
        self.assertFalse(out["ok"])

  def test_explicit_failure_remains_failed_with_complete_counts(self):
    self.loop["ok"] = False
    self.assertFalse(self.prove()["ok"])

  def test_loop_counts_must_be_integers(self):
    for value in ("24", 24.0, True, None):
      with self.subTest(passed=value):
        self.loop = {"passed": value, "loops": 24}
        self.assertFalse(self.prove()["ok"])

  def test_unrelated_signature_failure_still_blocks(self):
    self.coverage["signatures"]["ztfi_p4"] = "wrong"
    out = self.prove()
    self.assertFalse(out["checks"]["p4_sig"])
    self.assertFalse(out["ok"])


if __name__ == "__main__":
  unittest.main()
