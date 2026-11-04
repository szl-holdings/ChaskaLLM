# Security

Report a vulnerability or leaked credential privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open a public issue for secrets or exploitable defects.

## Scope

ChaskaLLM is the CPU Soft Shield mouth **source**. Public GGUF weights live on Hugging Face `SZLHOLDINGS/ChaskaLLM`. This repository does not accept credentials in chat, issue bodies, or sample configs.

## Secrets

- Never commit tokens, API keys, or private keys.
- Serving receipts and HF pins must use vaulted credentials outside the tree.
- If a secret is exposed, rotate it first, then open a private security advisory.

## Model / weight claims

Do not overwrite production weights without Stephen `GO WEIGHT`. Card-only or untrained artifacts must stay labeled `NOT_TRAINED` / `CARD_ONLY` — never stub-fill weights.
