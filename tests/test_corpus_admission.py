from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from chaskallm_ops.corpus_admission import admit_corpus, main

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
BASE_REVISION = "c" * 40


def _row(prompt: str, answer: str | None = "ok") -> dict:
    messages = [{"role": "user", "content": prompt}]
    if answer is not None:
        messages.append({"role": "assistant", "content": answer})
    return {"messages": messages}


class CorpusAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep fixtures beside the checkout so hermetic Windows runners do not
        # redirect the process-wide temp directory to a non-writable sandbox.
        self.temp = tempfile.TemporaryDirectory(prefix=".test-corpus-", dir=Path.cwd())
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_plan(self, train: list[dict], test: list[dict]) -> tuple[Path, str]:
        splits = {}
        for name, rows in (("train", train), ("test", test)):
            raw = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows).encode()
            path = self.root / f"{name}.jsonl"
            path.write_bytes(raw)
            splits[name] = {
                "path": path.name,
                "rows": len(rows),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        manifest = {
            "schema": "szl.forge-curriculum/v1",
            "training_eligible": True,
            "splits": splits,
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8", newline="\n")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def admit(self, path: Path, digest: str, **kwargs):
        return admit_corpus(
            path,
            manifest_sha256=digest,
            base_model=kwargs.pop("base_model", BASE_MODEL),
            base_revision=kwargs.pop("base_revision", BASE_REVISION),
            **kwargs,
        )

    def test_valid_plan_binds_manifest_base_and_disjoint_splits(self) -> None:
        path, digest = self.write_plan([_row("train prompt")], [_row("test prompt", None)])
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["manifest"]["sha256"], digest)
        self.assertEqual(report["base_model"]["revision"], BASE_REVISION)
        self.assertEqual(report["cross_split_overlaps"], 0)
        self.assertFalse(report["training_executed"])
        self.assertFalse(report["execution_authority"])
        self.assertFalse(report["publication_eligible"])

    def test_cli_emits_machine_readable_report_and_exit_status(self) -> None:
        path, digest = self.write_plan([_row("train")], [_row("test", None)])
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                str(path), "--manifest-sha256", digest,
                "--base-model", BASE_MODEL, "--base-revision", BASE_REVISION,
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "VALID")

    def test_manifest_and_split_bytes_are_exactly_bound(self) -> None:
        path, digest = self.write_plan([_row("train")], [_row("test", None)])
        self.assertEqual(self.admit(path, "0" * 64)["status"], "INVALID")
        (self.root / "train.jsonl").write_text("{}\n", encoding="utf-8")
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertTrue(any("declared sha256" in error for error in report["errors"]))

    def test_base_model_and_revision_cannot_be_placeholders(self) -> None:
        path, digest = self.write_plan([_row("train")], [_row("test", None)])
        for model, revision in (("Qwen3", BASE_REVISION), (BASE_MODEL, "main"), (BASE_MODEL, "0" * 40)):
            with self.subTest(model=model, revision=revision):
                self.assertEqual(
                    self.admit(path, digest, base_model=model, base_revision=revision)["status"],
                    "INVALID",
                )

    def test_exact_input_overlap_fails_despite_response_or_transport_changes(self) -> None:
        path, digest = self.write_plan(
            [_row("  caf\u00e9\r\nquestion  ", "train response")],
            [_row("cafe\u0301\nquestion", None)],
        )
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertEqual(report["cross_split_overlaps"], 1)

    def test_duplicate_train_inputs_with_different_answers_fail(self) -> None:
        path, digest = self.write_plan(
            [_row("same", "first"), _row("same", "second")],
            [_row("held out", None)],
        )
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertTrue(any("duplicate model input" in error for error in report["errors"]))

    def test_structure_and_declared_rows_fail_closed(self) -> None:
        path, digest = self.write_plan([{"messages": [{"role": "tool", "content": "x"}]}], [_row("test", None)])
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertTrue(any("unsupported role" in error for error in report["errors"]))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["splits"]["test"]["rows"] = 9
        path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        report = self.admit(path, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(any("row count" in error for error in report["errors"]))

    def test_split_path_cannot_escape_manifest_directory(self) -> None:
        path, _ = self.write_plan([_row("train")], [_row("test", None)])
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["splits"]["train"]["path"] = "../train.jsonl"
        path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertTrue(any("stay below" in error for error in report["errors"]))

    def test_duplicate_manifest_keys_are_rejected(self) -> None:
        path = self.root / "manifest.json"
        path.write_text('{"schema":"szl.one/v1","schema":"szl.two/v1","splits":{}}', encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        report = self.admit(path, digest)
        self.assertEqual(report["status"], "INVALID")
        self.assertTrue(any("duplicate JSON key" in error for error in report["errors"]))

    def test_manifest_policy_must_explicitly_allow_training_inputs(self) -> None:
        path, _ = self.write_plan([_row("train")], [_row("test", None)])
        for policy in (False, None, "true"):
            with self.subTest(policy=policy):
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if policy is None:
                    manifest.pop("training_eligible", None)
                else:
                    manifest["training_eligible"] = policy
                path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                report = self.admit(path, digest)
                self.assertEqual(report["status"], "INVALID")
                self.assertFalse(report["execution_authority"])


if __name__ == "__main__":
    unittest.main()
