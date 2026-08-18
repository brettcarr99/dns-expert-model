#!/usr/bin/env bash
# Fast path: download RFCs + vendor docs -> clean -> chunk -> embed/index ->
# register the Ollama model. Gets you a working dns-expert in ~20-40 minutes.
# Safe to re-run: each stage overwrites its own output / skips already-fetched files.
#
# Mailing list archives (IETF/DNS-OARC/RIPE) are a SEPARATE, much slower step
# -- see scripts/setup_discussions.sh. This script alone is enough to use
# dns-expert; discussions retrieval silently does nothing until that index
# exists (dns_expert/retrieval.py degrades gracefully if data/index_discussions/
# is missing), so there's no need to run it first.
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

echo "==> Downloading RFCs (~207 files, a couple of minutes)"
python3 scripts/download_rfcs.py

echo "==> Downloading vendor docs (~664 files across 11 products)"
python3 scripts/download_vendor_docs.py

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

echo "==> Registering the dns-expert Ollama model"
ollama create dns-expert -f Modelfile

echo
echo "Setup complete. Chat with it via:"
echo "  ./bin/dns-expert"
echo "or ask a one-off question:"
echo "  ./bin/dns-expert \"how do I enable DNSSEC in unbound?\""
echo
echo "Want it to also answer questions about a decade of IETF/DNS-OARC/RIPE"
echo "mailing list discussion? That's a separate, much slower step (the IETF"
echo "archive scraper paces itself respectfully, so it can take 10+ hours --"
echo "good to kick off overnight):"
echo "  ./scripts/setup_discussions.sh"
