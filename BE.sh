#!/bin/bash
# Start BIO backend server
# Usage: ./BE.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR"

python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
