#!/usr/bin/env bash
# Fast path for most users: download the pre-built vector indexes (already
# embedded from ~200 RFCs, 664 vendor doc files, and a decade of IETF/
# DNS-OARC/RIPE mailing list discussion) instead of re-downloading and
# rebuilding the whole corpus yourself. Pulls the base Ollama models and
# registers dns-expert. Takes a few minutes, not hours.
#
# If you'd rather build the corpus from scratch yourself (e.g. to refresh
# it with newer RFCs/docs, or audit exactly what's in it), use
# scripts/setup.sh + scripts/setup_discussions.sh instead -- that's the
# same thing this bundle was built with, just slower.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

RELEASE_TAG="${DNS_EXPERT_RELEASE_TAG:-v1.0.0}"
REPO="brettcarr99/dns-expert-model"
INDEX_URL="https://github.com/$REPO/releases/download/$RELEASE_TAG/dns-expert-index.tar.gz"
DISCUSSIONS_INDEX_URL="https://github.com/$REPO/releases/download/$RELEASE_TAG/dns-expert-discussions-index.tar.gz"

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

mkdir -p data

if [ -d data/index ]; then
  echo "==> data/index already exists, skipping download (delete it first to re-fetch)"
else
  echo "==> Downloading pre-built RFC/vendor-doc index (~36MB)"
  curl -fL "$INDEX_URL" -o /tmp/dns-expert-index.tar.gz
  tar -xzf /tmp/dns-expert-index.tar.gz -C data
  rm /tmp/dns-expert-index.tar.gz
fi

if [ -d data/index_discussions ]; then
  echo "==> data/index_discussions already exists, skipping download (delete it first to re-fetch)"
else
  echo "==> Downloading pre-built mailing-list-discussions index (~126MB)"
  curl -fL "$DISCUSSIONS_INDEX_URL" -o /tmp/dns-expert-discussions-index.tar.gz
  tar -xzf /tmp/dns-expert-discussions-index.tar.gz -C data
  rm /tmp/dns-expert-discussions-index.tar.gz
fi

echo "==> Registering the dns-expert Ollama model"
ollama create dns-expert -f Modelfile

echo
echo "Setup complete. Chat with it via:"
echo "  ./bin/dns-expert"
echo "or ask a one-off question:"
echo "  ./bin/dns-expert \"how do I enable DNSSEC in unbound?\""
