<!-- szl:header v1 -->
[![org: szl-holdings](https://img.shields.io/badge/org-szl--holdings-black)](https://github.com/szl-holdings)
[![doctrine](https://img.shields.io/badge/doctrine-control%20before%20action%20%C2%B7%20evidence%20after-blue)](https://a-11-oy.com)
[![hf](https://img.shields.io/badge/HF-SZLHOLDINGS%2FChaskaLLM-yellow)](https://huggingface.co/SZLHOLDINGS/ChaskaLLM)

**Control before action. Evidence after.**

Part of the [szl-holdings](https://github.com/szl-holdings) estate ·
Product: [a-11-oy.com](https://a-11-oy.com) ·
Proof: [a11oy.net](https://a11oy.net)
<!-- /szl:header -->

# ChaskaLLM

**Efficient CPU inference mouth for Soft Shield / edge agent stacks.**

**Face:** Stephen Lutar — CTO, SZL Holdings Inc  
**Hub weights:** [SZLHOLDINGS/ChaskaLLM](https://huggingface.co/SZLHOLDINGS/ChaskaLLM)  
**Try:** [chaskaclaw.com/chat](https://www.chaskaclaw.com/chat/)  
**Status:** Packaging + serving source in GitHub · GGUF weights on Hugging Face · **feature expansion deferred** per Stephen meeting priority reset (NVIDIA / InVerita / DARPA first)

## What this repo is

| Path | Role |
|------|------|
| `ops/chaskallm_api.py` | House GPU-less chat API (llama.cpp CPU, uploads, API keys) |
| `smoke/` | Honest smoke scope notes + mirrored receipt |
| `NOTICE` | Packaging Apache-2.0 vs upstream Qwen weight license reconciliation |
| Hugging Face GGUF | Large weights — **not** stored in Git |

## What this repo is not

- Not a from-scratch SZL base train receipt
- Not ChaskaClaw (OpenShell twin) and not NVIDIA NemoClaw
- Not an investor-complete product by itself (Stephen: repo + chat endpoint alone ≠ meeting demo)

## Model details

- Default base: `Qwen/Qwen3-4B-Instruct-2507` (`4b` lane, `chaskallm-4b.Q4_K_M.gguf` on Hugging Face)
- Retired base: `Qwen/Qwen2.5-3B-Instruct` (`3b` legacy lane; removed from Hugging Face main but still in its git history; chaskaclaw.com serves it until the 4B deploy)
- Quant: Q4_K_M GGUF (4B Soft Shield default)
- Runtime: llama.cpp `-ngl 0` (CPU)
- Naming lock: **ChaskaLLM** = mouth · **ChaskaClaw** = house OpenShell twin

## License

Code and weights are licensed separately, as `NOTICE` explains:

- **This repository’s code:** Apache-2.0 (`LICENSE`)
- **Upstream weights:** redistributed weights carry their upstream license; packaging Apache-2.0 does not re-license them
  - `chaskallm-4b.Q4_K_M.gguf`: upstream `Qwen/Qwen3-4B-Instruct-2507` and `unsloth/Qwen3-4B-Instruct-2507-GGUF` both declare `license: apache-2.0` on the Hub
  - `chaskallm-3b.Q4_K_M.gguf` (retired): upstream `Qwen/Qwen2.5-3B-Instruct` declares `license: other` / `license_name: qwen-research` on the Hub; Qwen research / upstream notices apply to it

This section reports upstream Hub metadata. It is not a legal determination.

## Smoke honesty

See `smoke/SMOKE-SCOPE.md`.

- **4B lane:** `smoke/SMOKE-4B-LATEST.json` (mirrored from Hugging Face), 7 / 7 checks passed on 2026-10-28.
- **Retired 3B build:** `smoke/SMOKE-HQ-LATEST.json` ends with `"pass": false`, because its internal 1.1B lane (`chat_fast_1b`) failed. Its public PASS badge covered the 3B lane only (`publication_badge: PASS_3B_ONLY`, `full_receipt_pass: false` in `smoke/SCOPE.json`). The failed case is preserved.

## Meeting priority note (2026-10-26)

Stephen deferred further Chaska feature/card expansion until after the October 30 InVerita meeting and NVIDIA hardware discussion. Critical path: A11oy, Killinchu, existing SZL models, NVIDIA / InVerita / DARPA tracks. This repo closes the **GitHub source gap** for ChaskaLLM while keeping it in the deferred column for feature work.
