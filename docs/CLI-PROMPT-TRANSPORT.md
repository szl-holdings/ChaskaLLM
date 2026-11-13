# CLI prompt transport and deployment compatibility

`whisper()` supplies caller text through a private temporary binary file. Only
the generated file path is passed as the value of `--binary-file`; prompt text
is absent from argv and process listings. Model selection remains allowlisted,
and the system prompt and generation options retain their existing values.
The 1.1B/tiny lanes retain `User: …\nAssistant:` formatting.

The file is created with mode `0600` inside a unique `0700` directory after a
generation slot is acquired. It remains available until the child exits or is
killed on timeout, then the context removes it and releases the slot. File or
spawn failures return `generation_io_error`; unsupported Unicode returns
`invalid_prompt_encoding`. These are failed results, never successful output.
An abrupt host/process termination can leave temporary files; this is ordinary
temporary-file cleanup, not secure erasure or crash-durable cleanup.

## Parser contract

The reviewed upstream implementation is
[llama.cpp `785322d17f2d51e5185cf996a1f4e46d87640841`, `common/arg.cpp`](https://github.com/ggml-org/llama.cpp/blob/785322d17f2d51e5185cf996a1f4e46d87640841/common/arg.cpp#L1787),
Git blob `e3ab084c67f942e02d8d22657cb4635634b2a250`.
Its `-bf` / `--binary-file` handler reads the entire file in binary mode into
the prompt. This preserves UTF-8 bytes and final newlines. The ordinary `--file`
handler removes one final newline and is not an equivalent replacement. Existing
llama.cpp prompt escape processing and chat templating still apply after parsing.

The source repository does not pin or attest the installed executable at
`/opt/alloyscape/vendor/llama.cpp/bin/llama-cli`. The reviewed upstream commit
is source evidence, not a claim that the deployed executable has that identity.

## Required compatibility evidence before deployment

An authorized operator must qualify the actual intended executable/build:

1. Record its SHA-256, `--version` output and the build/source provenance tying
   that binary to a reviewed parser. These are separate from the API Git SHA.
2. Inspect its `--help` output for `-bf` / `--binary-file`; confirm the argument
   takes a filename. Option presence alone is not semantic verification.
3. In an isolated staging environment, use non-sensitive fixed prompts with
   leading option text, Unicode, literal escape sequences and final newlines.
   Confirm the binary-file parser supplies the same prompt bytes as its direct
   prompt parser before model processing. Verify each intended model lane's
   chat-template behavior and record the binary/model identities and results.
4. Keep deployment on hold if identity, option support or byte semantics cannot
   be established. There is no fallback that puts caller text back into `-p`.

The automated regressions execute a local fixture program that reads argv and
the temporary file; they verify the Python process boundary, permissions,
concurrent isolation and cleanup. They do not execute llama.cpp, load models,
contact providers, attest a deployed binary or regenerate historical smoke
receipts. Existing deployment qualification remains required even if static
analysis no longer reports caller-controlled argv.
