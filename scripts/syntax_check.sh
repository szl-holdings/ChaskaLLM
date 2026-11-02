#!/usr/bin/env bash
set -euo pipefail
python3 -m py_compile ops/chaskallm_api.py
python3 -m py_compile chaskallm_ops/__init__.py chaskallm_ops/corpus_admission.py
echo SYNTAX_OK
