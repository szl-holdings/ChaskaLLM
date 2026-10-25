#!/usr/bin/env bash
set -euo pipefail
python3 -m py_compile ops/chaskallm_api.py
echo SYNTAX_OK
