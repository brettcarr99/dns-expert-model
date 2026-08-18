#!/usr/bin/env bash
# Full pipeline: clean corpus -> chunk -> embed/index (RFCs/vendor docs +
# mailing list archives) -> register Ollama model.
# Safe to re-run: each stage overwrites its own output.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama is not installed or not on PATH. Install it from https://ollama.com first." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "==> Creating venv"
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "==> Installing Python deps"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Pulling required Ollama models (skips if already present)"
ollama pull nomic-embed-text
ollama pull qwen2.5:32b-instruct
ollama pull lfm2.5:8b-a1b-q4_K_M

export PYTHONPATH="$DIR:${PYTHONPATH:-}"

echo "==> Cleaning RFCs"
python3 scripts/clean_rfcs.py

echo "==> Normalizing vendor docs"
python3 scripts/clean_vendor_docs.py

echo "==> Chunking corpus"
python3 scripts/build_chunks.py

echo "==> Enriching short/terse chunks with search paraphrases (this takes ~1 hour the first time)"
python3 scripts/enrich_chunks.py

echo "==> Embedding + building vector index (this takes a few minutes)"
python3 scripts/build_index.py

echo "==> Parsing IETF/DNS-OARC/RIPE mailing list archives"
python3 scripts/parse_discussions.py

echo "==> Chunking mailing list messages"
python3 scripts/build_discussion_chunks.py

echo "==> Embedding mailing list chunks into a separate index (~40k chunks, takes ~12 minutes)"
python3 scripts/build_discussions_index.py

echo "==> Registering the dns-expert Ollama model"
ollama create dns-expert -f Modelfile

echo
echo "Setup complete. Chat with it via:"
echo "  ./bin/dns-expert"
echo "or ask a one-off question:"
echo "  ./bin/dns-expert \"how do I enable DNSSEC in unbound?\""
echo
echo "Mailing list archive retrieval (IETF/DNS-OARC/RIPE) is on by default;"
echo "add --no-discussions to fall back to RFCs+vendor docs only."
