#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 -m venv .embedding-venv
.embedding-venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1+cpu torchvision==0.29.1+cpu
.embedding-venv/bin/python -m pip install -r requirements-search-lock.txt
.embedding-venv/bin/python app/download_embedding_model.py
