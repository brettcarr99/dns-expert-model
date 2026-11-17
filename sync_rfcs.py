#!/usr/bin/env python3
"""Incremental RFC sync — adds new DNS RFCs to the knowledge DB without re-embedding existing ones.

Usage:
    ~/gemini/dns-experts/.venv/bin/python ~/gemini/dns-experts/sync_rfcs.py

The script:
  1. Finds all rfc*.txt files in rfcs/clean/ not yet present in the DB (by source_id).
  2. Parses each with RFCParser (section-aware chunking).
  3. Skips any chunk whose source_id is already in the DB (upsert-safe).
  4. Embeds new chunks via OllamaClient.get_embedding().
  5. Batch-inserts into KnowledgeDB.
  6. Prints progress and a final summary.
"""

import sys
import os
import time
import sqlite3
from pathlib import Path

sys.path.insert(0, '/Users/brettcarr/gemini/dns-experts')

# Force correct Ollama host regardless of OLLAMA_HOST env var
os.environ.setdefault('OLLAMA_HOST', 'http://127.0.0.1:11434')
# Overwrite if it's the broken 0.0.0.0 value
if os.environ.get('OLLAMA_HOST', '').startswith('0.0.0.0'):
    os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:11434'

from dns_expert.knowledge.parsers.rfc_parser import RFCParser
from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.ollama_client import OllamaClient

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path('/Users/brettcarr/gemini/dns-experts')
CLEAN_DIR   = BASE_DIR / 'rfcs' / 'clean'
META_PATH   = BASE_DIR / 'rfcs' / 'metadata' / 'dns_rfcs_filtered.json'
DB_PATH     = BASE_DIR / 'dns_knowledge.db'

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_existing_source_ids(db_path: Path) -> set:
    """Return set of source_ids already present in the documents table."""
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT DISTINCT source_id FROM documents WHERE source_type = 'rfc';"
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


def embed_chunks(chunks, client: OllamaClient, batch_log_every: int = 10):
    """Embed a list of chunk dicts in-place; returns list with 'embedding' populated."""
    total = len(chunks)
    embedded = []
    for i, chunk in enumerate(chunks, 1):
        retries = 3
        for attempt in range(1, retries + 1):
            try:
                emb = client.get_embedding(chunk['content'])
                chunk['embedding'] = emb
                embedded.append(chunk)
                break
            except Exception as e:
                if attempt < retries:
                    wait = 2 ** attempt
                    print(f"      ↺ Embed retry {attempt}/{retries} for chunk {i} — {e}; waiting {wait}s")
                    time.sleep(wait)
                else:
                    print(f"      ✗ Embed FAILED for chunk {i} after {retries} attempts — {e}; skipping")
        if i % batch_log_every == 0 or i == total:
            print(f"    Embedded {i}/{total} chunks …")
    return embedded


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=" * 70)
    print("DNS Expert — Incremental RFC Sync")
    print("=" * 70)

    # 1. Connect to DB and get existing source_ids
    db = KnowledgeDB(DB_PATH, auto_unpack=False)
    existing_ids = get_existing_source_ids(DB_PATH)
    print(f"\n✓ DB opened — {len(existing_ids)} existing RFC source_ids")

    # 2. Find RFC files not yet in DB
    all_rfc_files = sorted(CLEAN_DIR.glob('rfc*.txt'))
    new_files = []
    for f in all_rfc_files:
        import re
        m = re.search(r'rfc(\d+)', f.name, re.IGNORECASE)
        if not m:
            continue
        sid = f'rfc{m.group(1)}'
        if sid not in existing_ids:
            new_files.append(f)

    print(f"✓ Found {len(all_rfc_files)} RFC files in rfcs/clean/")
    print(f"✓ {len(new_files)} new RFC files not yet in DB\n")

    if not new_files:
        print("Nothing to do — DB is already up to date.")
        return

    # 3. Parse all new files
    parser = RFCParser(rfc_dir=CLEAN_DIR, metadata_path=META_PATH)
    client = OllamaClient()

    if not client.check_health():
        print("✗ Ollama is not reachable at the configured host. Please start it.")
        sys.exit(1)
    print(f"✓ Ollama health check passed (embed model: {client.embed_model})\n")

    total_new_chunks   = 0
    total_new_rfcs     = 0
    skipped_rfcs       = 0
    failed_rfcs        = []
    start_total        = db.get_stats()['total_chunks']

    for file_idx, rfc_file in enumerate(new_files, 1):
        import re
        m = re.search(r'rfc(\d+)', rfc_file.name, re.IGNORECASE)
        rfc_num = m.group(1) if m else '?'
        source_id = f'rfc{rfc_num}'

        print(f"[{file_idx:3d}/{len(new_files)}] {source_id}  ({rfc_file.name})")

        # Double-check in case a previous partial run inserted some chunks
        # (upsert-safety: skip if ANY chunk for this source_id already exists)
        con = sqlite3.connect(str(DB_PATH))
        existing_count = con.execute(
            "SELECT COUNT(*) FROM documents WHERE source_id = ?;", (source_id,)
        ).fetchone()[0]
        con.close()

        if existing_count > 0:
            print(f"    ↷ Already in DB ({existing_count} chunks) — skipping")
            skipped_rfcs += 1
            continue

        # Parse
        try:
            chunks = parser.parse_file(rfc_file)
        except Exception as e:
            print(f"    ✗ Parse failed: {e}")
            failed_rfcs.append((source_id, str(e)))
            continue

        if not chunks:
            print(f"    ⚠ No chunks produced — skipping")
            continue

        print(f"    → {len(chunks)} chunks parsed  — embedding …")

        # Embed
        embedded_chunks = embed_chunks(chunks, client, batch_log_every=20)

        if not embedded_chunks:
            print(f"    ✗ All embeddings failed — skipping")
            failed_rfcs.append((source_id, "all embeddings failed"))
            continue

        # Insert
        inserted = db.insert_chunks_batch(embedded_chunks)
        total_new_chunks += inserted
        total_new_rfcs   += 1
        print(f"    ✓ Inserted {inserted} chunks  (running total: {total_new_chunks})")

    # 4. Final summary
    elapsed = time.time() - t0
    end_total = db.get_stats()['total_chunks']

    print("\n" + "=" * 70)
    print("SYNC COMPLETE")
    print("=" * 70)
    print(f"  New RFC files processed : {total_new_rfcs}")
    print(f"  New chunks added        : {total_new_chunks}")
    print(f"  RFCs skipped (dup)      : {skipped_rfcs}")
    print(f"  RFCs failed             : {len(failed_rfcs)}")
    if failed_rfcs:
        for sid, err in failed_rfcs:
            print(f"    - {sid}: {err}")
    print(f"  DB total before         : {start_total:,}")
    print(f"  DB total after          : {end_total:,}")
    print(f"  Elapsed                 : {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print("=" * 70)


if __name__ == '__main__':
    main()
