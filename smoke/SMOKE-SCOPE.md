# Smoke scope (honest)

Public claims for the retired 3B Soft Shield default were scoped to the **3B** lane.

The full HQ smoke receipt may include an internal **1.1B** lane failure (`chat_fast_1b`).
That does **not** mean the 3B model is broken. Do not publish an unqualified estate-wide PASS badge that swallows the failed case.

See `SMOKE-HQ-LATEST.json` (mirrored from HF when available) and preserve fails.

## 2026-10-28: 4B default

The Soft Shield default is now the `4b` lane (`Qwen/Qwen3-4B-Instruct-2507`). Its receipt is
`SMOKE-4B-LATEST.json`, mirrored byte for byte from Hugging Face: 7 / 7 checks passed.

`SCOPE.json` and `SMOKE-HQ-LATEST.json` stay as the record of the retired 3B build. That full
receipt is `"pass": false`, and its PASS badge (`PASS_3B_ONLY`) covered the 3B lane only.
