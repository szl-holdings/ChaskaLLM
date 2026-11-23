# Leader-Study Upgrade Plan - W27 loop-3 - 2026-11-23

Status: PROPOSE-ONLY DRAFT - DO NOT MERGE. Owner-gated: merging requires governing approval and the estate signature-wall owner unlock.

Repo: ChaskaLLM - ChaskaLLM — CPU Soft Shield mouth (source). Weights on HF SZLHOLDINGS/ChaskaLLM. Feature expansion deferred.

Frame: OUROBOROS loop-3 leader study. Governing seat: Kimi kimi-k3.1-pro (json_ok, think off). Advisory seats: Astra/Sol/Claude community rails (provenance unverified, advisory only). Leader evidence web-verified 2026-11-23.

## Leader moats to absorb
- llama.cpp: Direct CPU inference engine for GGUF models, used by ChaskaLLM with -ngl 0. Moat: Low-level control over CPU inference and a reported ~4.4 percent Q4-Q5 GGUF throughput edge over Ollama in the supplied AIMEC 2026 benchmark.
- Ollama: Managed local model service with an OpenAI-like API. Moat: Operational simplicity and familiar managed-model serving rather than maximum direct inference control.
- NeMo Guardrails: NVIDIA framework for adding programmable guardrails around LLM applications. Moat: Dedicated conversational-control layer backed by NVIDIA's AI ecosystem.
- Llama Guard 3: Meta safety model for classifying risky prompts and responses. Moat: Model-based safety classification that can complement deterministic application controls.
- LLM Guard: Protect AI toolkit of input and output scanners for LLM applications. Moat: Composable scanning coverage across both sides of an LLM interaction.
- Guardrails AI: Validation framework and validator hub for checking model outputs. Moat: Reusable validators and an ecosystem for structured output assurance.

## Honest gaps (grounded in repo facts)
- Feature expansion is explicitly deferred, so none of these leader-inspired additions is established as present in the repository.
- The facts identify llama.cpp CPU inference, uploads, API keys, and prompt-file transport, but do not establish input/output safety scanners comparable to LLM Guard.
- The facts do not establish a model-based prompt/response safety classifier comparable to Llama Guard 3.
- The facts do not establish programmable conversational guardrails comparable to NeMo Guardrails.
- The facts do not establish reusable output validators comparable to Guardrails AI.
- The supplied smoke section is truncated, so its executed commands, environment, results, and receipt contents cannot be verified here; no smoke success should be inferred.
- The README distinguishes packaging source from weights and says this is not a from-scratch SZL base-train receipt; the repository therefore does not by itself evidence base-model training.
- The README says the repository plus chat endpoint is not an investor-complete product or meeting demo by itself.
- The 3B lane is retired and removed from Hugging Face main but remains in its git history, while chaskaclaw.com serves it until the 4B deploy; the facts do not prove that the 4B deployment cutover is complete.
- The 4B and retired 3B weights have different upstream license metadata, so any future weight or lane change needs license reconciliation rather than assuming repository Apache-2.0 covers all weights.
- No comparative benchmark for ChaskaLLM itself is supplied; the cited ~4.4 percent figure is a web-verified llama.cpp-versus-Ollama result, not a measured ChaskaLLM advantage.

## Dosed upgrade plan
- Dose 0 — evidence only: inventory the existing API, smoke scope, mirrored receipt, prompt-transport contract, deployment configuration, and current 3B/4B serving state; record what is actually executed and leave behavior unchanged.
- Dose 1 — propose a baseline reproducibility packet: pinned runtime and model identifiers, CPU-only settings, prompt-file compatibility checks, latency/throughput measurements, upload and API-key negative tests, and explicit smoke limitations; do not claim results before running them.
- Dose 2 — propose a deployment-cutover decision record for retiring the legacy 3B service, including weight-license reconciliation, history-retention treatment, rollback, and endpoint verification; obtain owner approval before changing service.
- Dose 3 — behind a disabled-by-default experiment flag, prototype one structured-output validation path inspired by Guardrails AI and measure CPU overhead and failure behavior; propose only until separately approved.
- Dose 4 — separately evaluate LLM Guard scanners and Llama Guard 3 on representative input/output cases, documenting detections, false positives, latency, memory, licenses, and fail-open/fail-closed behavior; do not enable enforcement in this dose.
- Dose 5 — assess whether NeMo Guardrails adds necessary policy orchestration beyond the validated controls, avoiding framework adoption merely for feature parity.
- Dose 6 — only after owner reprioritization, propose one minimal hardened serving release with approved controls, explicit defaults, receipts, rollback, and refreshed README/NOTICE/smoke scope; keep any Ollama comparison or alternate serving lane optional and evidence-led.
- Risk note: The largest near-term risks are overstating unverified smoke or benchmark evidence, accidentally treating packaging Apache-2.0 as a re-license of upstream weights, and disrupting the legacy-to-4B cutover. Guardrail additions can increase CPU latency and memory, introduce false positives or bypasses, leak sensitive prompts/responses to added components, and create a false assurance of safety. Managed-serving changes can also weaken direct llama.cpp control and prompt-transport compatibility. Mitigate with disabled-by-default experiments, separate code/weight license checks, measured baselines, adversarial and failure-mode tests, explicit fail-closed decisions where warranted, receipts, and rollback.
- Propose-only note: Feature expansion is deferred per the owner priority reset. This is an audit and proposal, not authorization to modify the repository, endpoint, weights, dependencies, or production policy. Each dose requires explicit owner approval, a bounded change set, and evidence after execution.

## Advisory notes (unverified rails, non-binding)
- astra: ci-witness-action: Cryptographic provenance standards (SLSA/in-toto) amaru: W3C Trace Context specification authority ChaskaLLM: Hardware-level memory safety primitives
- sol: ci-witness-action: Cryptographic non-repudiation of build provenance. amaru: Standardized observability for distributed trace propagation. ChaskaLLM: Deterministic resource-constrained inference guarantees.
- claude: ci-witness-action: Cryptographic provenance standards for supply-chain attestation. amaru: W3C distributed tracing interoperability benchmarks. ChaskaLLM: Hardware-level memory isolation for inference kernels.

## DO NOT MERGE
This plan is a proposal artifact of the 10-pass OUROBOROS loop (loop-3 of 10). No code, no CI, no behavior changes in this file. A reviewer with authority may convert to a work order later.