#!/usr/bin/env python3
"""Validate a bound Forge-style corpus split manifest before training.

The command is deliberately stdlib-only and offline. It validates source
identity, bytes, structure, duplicate inputs, and exact train/held-out overlap.
It emits an admission report; it does not train, publish, or promote a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

REPORT_SCHEMA = "szl.chaskallm-corpus-admission/v1"
FINGERPRINT_SCHEMA = "sha256-canonical-chat-input-v1"
ALLOWED_ROLES = frozenset({"system", "user", "assistant"})
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_SCHEMA = re.compile(r"^szl\.[A-Za-z0-9._-]+/v[0-9]+$")
MAX_ERRORS = 25


class DuplicateKeyError(ValueError):
    """Raised when JSON repeats a key and would otherwise hide a value."""


def _strict_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _read_json(path: Path) -> Any:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_strict_object)


def _hex_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.removeprefix("sha256:").lower()
    return normalized if HEX_64.fullmatch(normalized) else None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", value).strip()


def _input_fingerprint(messages: Sequence[dict[str, str]]) -> str:
    inputs = [
        {"role": message["role"], "content": _normalize_text(message["content"])}
        for message in messages
        if message["role"] != "assistant"
    ]
    canonical = json.dumps(
        inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _bounded_path(root: Path, declared: Any) -> Path:
    if not isinstance(declared, str) or not declared or "\\" in declared:
        raise ValueError("split path must be a non-empty portable relative path")
    relative = Path(declared)
    if (
        relative.is_absolute()
        or declared != relative.as_posix()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("split path must stay below the manifest directory")
    root_resolved = root.resolve()
    candidate = (root / relative).resolve(strict=True)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("split path escapes the manifest directory") from exc
    if not candidate.is_file():
        raise ValueError("split path is not a regular file")
    return candidate


def _read_split(path: Path, *, require_assistant: bool) -> dict[str, Any]:
    errors: list[str] = []
    fingerprints: dict[str, int] = {}
    digest = hashlib.sha256()
    duplicate_inputs = 0
    records = 0
    try:
        handle = path.open("rb")
    except OSError as exc:
        return {
            "sha256": None,
            "records": 0,
            "fingerprints": {},
            "duplicate_inputs": 0,
            "errors": [f"unreadable split: {exc}"],
        }
    with handle:
      for line_number, raw_line in enumerate(handle, 1):
        digest.update(raw_line)
        if not raw_line.strip():
            continue
        records += 1
        try:
            line = raw_line.decode("utf-8", errors="strict")
            row = json.loads(line, object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
            errors.append(f"line {line_number}: invalid UTF-8 or JSON ({exc})")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {line_number}: record is not an object")
            continue
        messages = row.get("messages")
        if not isinstance(messages, list) or not messages:
            errors.append(f"line {line_number}: missing or empty messages")
            continue
        checked: list[dict[str, str]] = []
        roles: set[str] = set()
        valid = True
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                errors.append(f"line {line_number}: message {index} is not an object")
                valid = False
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in ALLOWED_ROLES:
                errors.append(f"line {line_number}: message {index} has unsupported role")
                valid = False
            if not isinstance(content, str) or not content.strip():
                errors.append(f"line {line_number}: message {index} has empty content")
                valid = False
            if isinstance(role, str) and isinstance(content, str):
                checked.append({"role": role, "content": content})
                roles.add(role)
        if not valid:
            continue
        if "user" not in roles or (require_assistant and "assistant" not in roles):
            requirement = "user and assistant" if require_assistant else "user"
            errors.append(f"line {line_number}: record requires {requirement} messages")
            continue
        fingerprint = _input_fingerprint(checked)
        if fingerprint in fingerprints:
            duplicate_inputs += 1
            errors.append(
                f"line {line_number}: duplicate model input (same canonical input as line "
                f"{fingerprints[fingerprint]})"
            )
        else:
            fingerprints[fingerprint] = line_number
    return {
        "sha256": digest.hexdigest(),
        "records": records,
        "fingerprints": fingerprints,
        "duplicate_inputs": duplicate_inputs,
        "errors": errors,
    }


def admit_corpus(
    manifest_path: str | Path,
    *,
    manifest_sha256: str,
    base_model: str,
    base_revision: str,
    train_split: str = "train",
    heldout_splits: Sequence[str] = ("test",),
) -> dict[str, Any]:
    """Return a fail-closed report for one exact corpus/base-model binding."""
    errors: list[str] = []
    manifest_file = Path(manifest_path)
    manifest_digest: str | None = None
    manifest: Any = None
    declared_manifest_digest = _hex_digest(manifest_sha256)
    if declared_manifest_digest is None:
        errors.append("manifest_sha256 must be one exact SHA-256 digest")
    try:
        manifest_raw = manifest_file.read_bytes()
        manifest_digest = _sha256(manifest_raw)
        manifest = json.loads(
            manifest_raw.decode("utf-8", errors="strict"), object_pairs_hook=_strict_object
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        errors.append(f"manifest is unreadable or invalid: {exc}")
    if declared_manifest_digest and manifest_digest != declared_manifest_digest:
        errors.append("manifest bytes do not match manifest_sha256")
    if not MODEL_ID.fullmatch(base_model or ""):
        errors.append("base_model must be an exact owner/repository identifier")
    normalized_revision = (base_revision or "").lower()
    if not GIT_SHA.fullmatch(normalized_revision) or normalized_revision == "0" * 40:
        errors.append("base_revision must be one non-zero 40-hex Git revision")
    if not isinstance(train_split, str) or not train_split:
        errors.append("train_split must be named")
    if not heldout_splits or any(not isinstance(name, str) or not name for name in heldout_splits):
        errors.append("at least one named held-out split is required")
    if len(set(heldout_splits)) != len(heldout_splits):
        errors.append("held-out split names must be unique")
    if train_split in heldout_splits:
        errors.append("training and held-out split names must differ")

    split_reports: dict[str, dict[str, Any]] = {}
    split_inputs: dict[str, dict[str, int]] = {}
    if manifest is not None:
        if not isinstance(manifest, dict):
            errors.append("manifest root must be an object")
        else:
            schema = manifest.get("schema")
            if not isinstance(schema, str) or not SOURCE_SCHEMA.fullmatch(schema):
                errors.append("manifest needs a versioned szl.* schema")
            if manifest.get("training_eligible") is not True:
                errors.append("manifest must explicitly declare training_eligible true")
            splits = manifest.get("splits")
            if not isinstance(splits, dict):
                errors.append("manifest needs a splits object")
            else:
                for name in (train_split, *heldout_splits):
                    declared = splits.get(name)
                    report: dict[str, Any] = {"status": "INVALID"}
                    split_reports[name] = report
                    if not isinstance(declared, dict):
                        errors.append(f"split {name!r} is missing or not an object")
                        continue
                    declared_digest = _hex_digest(declared.get("sha256"))
                    declared_rows = declared.get("rows")
                    if declared_digest is None:
                        errors.append(f"split {name!r} needs an exact sha256")
                    if type(declared_rows) is not int or declared_rows < 1:
                        errors.append(f"split {name!r} needs a positive integer row count")
                    try:
                        path = _bounded_path(manifest_file.parent, declared.get("path"))
                        parsed = _read_split(path, require_assistant=name == train_split)
                    except (OSError, ValueError) as exc:
                        errors.append(f"split {name!r} is unavailable: {exc}")
                        continue
                    actual_digest = parsed["sha256"]
                    report.update({
                        "path": declared.get("path"),
                        "records": parsed["records"],
                        "sha256": actual_digest,
                        "duplicate_inputs": parsed["duplicate_inputs"],
                    })
                    if declared_digest and actual_digest != declared_digest:
                        errors.append(f"split {name!r} bytes do not match its declared sha256")
                    if type(declared_rows) is int and parsed["records"] != declared_rows:
                        errors.append(f"split {name!r} row count does not match its declaration")
                    errors.extend(f"split {name!r}: {error}" for error in parsed["errors"])
                    split_inputs[name] = parsed["fingerprints"]
                    report["status"] = "VALID" if not parsed["errors"] else "INVALID"

    overlaps = 0
    train_inputs = split_inputs.get(train_split, {})
    for name in heldout_splits:
        common = sorted(set(train_inputs).intersection(split_inputs.get(name, {})))
        overlaps += len(common)
        if name in split_reports:
            split_reports[name]["overlapping_train_inputs"] = len(common)
        for fingerprint in common:
            errors.append(
                f"train line {train_inputs[fingerprint]} overlaps held-out split {name!r} "
                f"line {split_inputs[name][fingerprint]}"
            )

    report = {
        "schema": REPORT_SCHEMA,
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "status": "VALID" if not errors else "INVALID",
        "manifest": {
            "path": str(manifest_file),
            "sha256": manifest_digest,
            "declared_sha256": declared_manifest_digest,
            "source_schema": manifest.get("schema") if isinstance(manifest, dict) else None,
            "training_eligible": manifest.get("training_eligible") if isinstance(manifest, dict) else None,
        },
        "base_model": {"repository": base_model, "revision": normalized_revision},
        "train_split": train_split,
        "heldout_splits": list(heldout_splits),
        "cross_split_overlaps": overlaps,
        "splits": split_reports,
        "training_executed": False,
        "execution_authority": False,
        "publication_eligible": False,
        "errors": errors[:MAX_ERRORS],
    }
    if len(errors) > MAX_ERRORS:
        report["errors_truncated"] = len(errors) - MAX_ERRORS
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Forge-style split manifest")
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--base-model", required=True, help="exact owner/repository")
    parser.add_argument("--base-revision", required=True, help="exact non-zero 40-hex revision")
    parser.add_argument("--train-split", default="train")
    parser.add_argument("--heldout-split", action="append", dest="heldout_splits", default=[])
    args = parser.parse_args(argv)
    report = admit_corpus(
        args.manifest,
        manifest_sha256=args.manifest_sha256,
        base_model=args.base_model,
        base_revision=args.base_revision,
        train_split=args.train_split,
        heldout_splits=args.heldout_splits or ["test"],
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
