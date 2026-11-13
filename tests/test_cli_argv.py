"""A NUL byte in a caller prompt must not crash generation.

Run: python3 -m unittest discover -s tests -v
Subprocess refuses argv strings containing NUL. Prompts travel through a
private binary file, preserving NUL bytes without putting them in argv. The
argv is handed to a real child process (Python, not llama.cpp), so OS argv
rules still apply.
No model, llama.cpp binary or network is needed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

os.environ.setdefault("CHASKA_DATA_DIR", tempfile.mkdtemp(prefix="chaska-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import chaskallm_api as api  # noqa: E402

REAL_WHISPER = api.whisper


class CliArgvTest(unittest.TestCase):
  def setUp(self) -> None:
    temporary = tempfile.TemporaryDirectory(prefix="chaska-argv-")
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)

  def test_nul_bytes_in_a_prompt_never_reach_the_cli_argv(self) -> None:
    cli = self.root / "llama-cli"
    model = self.root / "3b.gguf"
    cli.write_bytes(b"x")
    model.write_bytes(b"x")
    seen: list[list[str]] = []
    payloads: list[bytes] = []
    real_run = subprocess.run

    def run_child(cmd, **kwargs):
      seen.append(list(cmd))
      payloads.append(Path(cmd[cmd.index("--binary-file") + 1]).read_bytes())
      # Same argv to a real child process, so the OS argv rules (no NUL bytes) apply.
      return real_run([sys.executable, "-c", "print('Assistant: ok')", *cmd[1:]], **kwargs)

    with mock.patch.object(api, "CLI", cli), mock.patch.dict(api.MODELS, {"3b": model}), \
        mock.patch.object(api.subprocess, "run", side_effect=run_child):
      out = REAL_WHISPER("hel\x00lo", model_key="3b")
    self.assertTrue(out["ok"], out)
    self.assertEqual(out["text"], "ok")
    self.assertEqual(len(seen), 1)
    self.assertNotIn("\x00", "".join(seen[0]))
    self.assertNotIn("-p", seen[0])
    self.assertEqual(payloads, [b"hel\x00lo"])


if __name__ == "__main__":
  unittest.main()
