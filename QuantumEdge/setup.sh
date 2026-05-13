#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
if [[ "${OS:-}" == "Windows_NT" ]]; then
  .venv/Scripts/python -m pip install --upgrade pip
  .venv/Scripts/pip install -r requirements.txt
else
  . .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
fi
cp -n .env.example .env || true
mkdir -p logs data
echo "QuantumEdge setup complete. Edit .env, then run: streamlit run dashboard.py"
