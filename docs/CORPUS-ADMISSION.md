# Corpus admission contract

`chaska-corpus-admit` is an offline preflight for a proposed ChaskaLLM
training corpus. It accepts a Forge-style JSON manifest with a versioned
`szl.*` schema and a `splits` object. Each selected split must declare a
portable relative `path`, positive `rows`, and exact SHA-256 digest.
The manifest must explicitly declare `training_eligible: true`; missing,
false or string-valued policy is rejected.

The caller must also bind the manifest bytes and base-model source:

```bash
chaska-corpus-admit path/to/curriculum-manifest.json \
  --manifest-sha256 <64-hex-digest> \
  --base-model Qwen/Qwen3-4B-Instruct-2507 \
  --base-revision <40-hex-git-revision> \
  --train-split train \
  --heldout-split test
```

Admission fails when the manifest or split bytes drift, row counts disagree,
chat records are malformed, a model input is duplicated, a selected held-out
split overlaps the training inputs, or the base model is not bound to one exact
revision. Input fingerprints normalize Unicode and newline transport while
excluding assistant responses, so changing a label cannot hide a repeated
prompt.

The JSON result is a source/data admission receipt only. It explicitly records
`training_executed: false`, `execution_authority: false` and
`publication_eligible: false`. Exact-input
disjointness does not detect paraphrases, memorization in the base model,
licensing or consent defects, evaluation quality, scientific validity, or
deployment state. Those remain separate gates.
