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

- Base: `Qwen/Qwen2.5-3B-Instruct`
- Quant: Q4_K_M GGUF (3B Soft Shield default)
- Runtime: llama.cpp `-ngl 0` (CPU)
- Naming lock: **ChaskaLLM** = mouth · **ChaskaClaw** = house OpenShell twin

## License

- **This repository’s code:** Apache-2.0 (`LICENSE`)
- **Upstream weights:** see `NOTICE` — Qwen research / upstream notices apply to redistributed weights; packaging Apache-2.0 does not re-license them

## Smoke honesty

See `smoke/SMOKE-SCOPE.md`. Public PASS claims are scoped to the **3B** lane; preserve any failed internal 1.1B checks in the full receipt.

## Meeting priority note (2026-10-26)

Stephen deferred further Chaska feature/card expansion until after the October 30 InVerita meeting and NVIDIA hardware discussion. Critical path: A11oy, Killinchu, existing SZL models, NVIDIA / InVerita / DARPA tracks. This repo closes the **GitHub source gap** for ChaskaLLM while keeping it in the deferred column for feature work.
