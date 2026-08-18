#!/usr/bin/env bash
# Slow path: download IETF dnsop/dns-privacy/dd + DNS-OARC dns-operations +
# RIPE DNS WG mailing list archives (2016-2026) -> parse -> chunk -> embed
# into a separate index. Requires scripts/setup.sh to have been run first
# (venv, Python deps, PYTHONPATH).
#
# HEAVILY RATE-LIMITED ON PURPOSE. The IETF mail archive scraper paces
# itself at roughly one request per 1.2-2 seconds with exponential backoff
# on HTTP 429, out of respect for mailarchive.ietf.org -- for dnsop's
# ~21,000 messages alone that's realistically 10+ hours. This is meant to
# be started and left running (e.g. overnight), not watched.
#
# Safe to re-run/resume: every download script skips files it already has,
# so an interrupted run just picks back up.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

if [ ! -d .venv ]; then
  echo "ERROR: .venv not found -- run ./scripts/setup.sh first." >&2
  exit 1
fi
source .venv/bin/activate
export PYTHONPATH="$DIR:${PYTHONPATH:-}"

echo "==> Downloading IETF dnsop/dns-privacy/dd mailing list archives"
echo "    (this is the slow part -- can take 10+ hours for dnsop alone)"
python3 scripts/download_ietf_discussions.py

echo "==> Downloading DNS-OARC dns-operations archive"
python3 scripts/download_dns_oarc_discussions.py

echo "==> Downloading RIPE DNS WG archive"
python3 scripts/download_ripe_discussions.py

echo "==> Parsing archives into cleaned messages"
python3 scripts/parse_discussions.py

echo "==> Chunking messages"
python3 scripts/build_discussion_chunks.py

echo "==> Embedding into a separate index (~40k chunks, ~12 minutes)"
python3 scripts/build_discussions_index.py

echo
echo "Mailing list archives indexed. ./bin/dns-expert now draws on them by"
echo "default -- add --no-discussions to fall back to RFCs+vendor docs only."
