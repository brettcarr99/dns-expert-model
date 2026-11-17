#!/usr/bin/env python3
"""Incremental RFC sync — adds new DNS RFCs to the knowledge DB without re-embedding existing ones.

Usage:
    ~/dns-experts/.venv/bin/python ~/dns-experts/sync_rfcs.py

The script:
  1. Finds all rfc*.txt files in rfcs/clean/ not yet present in the DB (by source_id).
  2. Parses each with RFCParser (section-aware chunking).
  3. Skips any chunk whose source_id+content_hash is already in the DB (upsert-safe).
  4. Embeds new chunks via OllamaClient.get_embedding().
  5. Batch-inserts into KnowledgeDB.
  6. Marks obsoleted RFCs with [OBSOLETED by RFCxxxx] prefix on titles.
  7. Updates sync_state table and writes corpus_manifest.json.
  8. Prints progress and a final summary.
"""

import json
import re
import sys
import os
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
BASE_DIR = Path('/Users/brettcarr/dns-experts')
sys.path.insert(0, str(BASE_DIR))

# Force correct Ollama host regardless of OLLAMA_HOST env var
os.environ.setdefault('OLLAMA_HOST', 'http://127.0.0.1:11434')
if os.environ.get('OLLAMA_HOST', '').startswith('0.0.0.0'):
    os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:11434'

from dns_expert.knowledge.parsers.rfc_parser import RFCParser
from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.ollama_client import OllamaClient
from dns_expert.config import EMBED_MODEL, EMBEDDING_DIM

# ── Paths ──────────────────────────────────────────────────────────────────────
CLEAN_DIR     = BASE_DIR / 'rfcs' / 'clean'
META_PATH     = BASE_DIR / 'rfcs' / 'metadata' / 'dns_rfcs_filtered.json'
DB_PATH       = BASE_DIR / 'dns_knowledge.db'
MANIFEST_PATH = BASE_DIR / 'corpus_manifest.json'

# ── Known obsolescence pairs (source_id → superseded-by source_id)
# Source: RFC Editor status pages. Supplements metadata when 'obsoleted_by' field absent.
_KNOWN_OBSOLETE: dict = {
    'rfc2845': 'rfc8945',   # TSIG: RFC 2845 obsoleted by RFC 8945
    'rfc5966': 'rfc7766',   # DNS TCP transport: RFC 5966 obsoleted by RFC 7766
    'rfc2671': 'rfc6891',   # EDNS0: RFC 2671 obsoleted by RFC 6891
    'rfc2535': 'rfc4033',   # DNSSEC: RFC 2535 obsoleted by RFC 4033/4034/4035
    'rfc2065': 'rfc2535',   # DNS Security Extensions: RFC 2065 obsoleted by RFC 2535
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_rfc_metadata(meta_path: Path) -> dict:
    """Load DNS RFC metadata JSON and index by source_id ('rfc1234')."""
    if not meta_path.exists():
        return {}
    raw = json.loads(meta_path.read_text())
    # Support both list and dict formats
    if isinstance(raw, list):
        return {f"rfc{entry['rfc']}": entry for entry in raw if 'rfc' in entry}
    return raw


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


def build_corpus_manifest(db: KnowledgeDB, rfc_meta: dict, sync_ts: str) -> dict:
    """Build the corpus_manifest.json structure from the current DB state."""
    stats = db.get_stats()
    sync_state = db.get_sync_state('rfc')

    # Collect per-RFC source info (one representative row per source_id)
    sources = []
    with db._get_connection() as con:
        rows = con.execute("""
            SELECT source_id, title, date, url_or_path, content_hash
            FROM documents
            WHERE source_type = 'rfc'
            GROUP BY source_id
            ORDER BY source_id;
        """).fetchall()
        for row in rows:
            sid = row['source_id']
            sources.append({
                'source_id': sid,
                'title': row['title'],
                'content_hash': row['content_hash'] or '',
                'fetch_date': rfc_meta.get(sid, {}).get('year', ''),
                'url': row['url_or_path'] or f'https://www.rfc-editor.org/rfc/{sid}.txt',
            })

    rfc_count = len(sources)

    manifest = {
        'generated_at': sync_ts,
        'embed_model': EMBED_MODEL,
        'total_chunks': stats['total_chunks'],
        'by_source': stats.get('by_source', {}),
        'rfc_count': rfc_count,
        'last_rfc_sync': sync_state['last_sync_ts'] if sync_state else sync_ts,
        'sources': sources,
    }
    return manifest


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    sync_ts = datetime.now(timezone.utc).isoformat()

    print("=" * 70)
    print("DNS Expert — Incremental RFC Sync")
    print("=" * 70)

    # 1. Connect to DB
    db = KnowledgeDB(DB_PATH, auto_unpack=False)
    rfc_meta = load_rfc_metadata(META_PATH)
    print(f"\n✓ Loaded {len(rfc_meta)} RFC metadata entries")

    existing_ids = db.get_existing_source_ids(source_type='rfc')
    print(f"✓ DB opened — {len(existing_ids)} existing RFC source_ids")

    # 2. Find RFC files not yet in DB
    all_rfc_files = sorted(CLEAN_DIR.glob('rfc*.txt'))
    new_files = []
    for f in all_rfc_files:
        m = re.search(r'rfc(\d+)', f.name, re.IGNORECASE)
        if not m:
            continue
        sid = f'rfc{m.group(1)}'
        if sid not in existing_ids:
            new_files.append(f)

    print(f"✓ Found {len(all_rfc_files)} RFC files in rfcs/clean/")
    print(f"✓ {len(new_files)} new RFC files not yet in DB\n")

    if not new_files:
        print("Nothing new to embed — DB is already up to date.")
    else:
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
            m = re.search(r'rfc(\d+)', rfc_file.name, re.IGNORECASE)
            rfc_num = m.group(1) if m else '?'
            source_id = f'rfc{rfc_num}'

            print(f"[{file_idx:3d}/{len(new_files)}] {source_id}  ({rfc_file.name})")

            # Double-check for partial previous run
            with db._get_connection() as con:
                existing_count = con.execute(
                    "SELECT COUNT(*) FROM documents WHERE source_id = ?;", (source_id,)
                ).fetchone()[0]

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

        elapsed_embed = time.time() - t0
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
        print(f"  Elapsed                 : {elapsed_embed:.1f}s ({elapsed_embed/60:.1f} min)")
        print("=" * 70)

    # 4. Mark obsoleted RFCs
    print("\n── Obsolescence marking ──────────────────────────────────────────────")
    all_db_ids = db.get_existing_source_ids(source_type='rfc')
    total_marked = 0

    # Build obsolescence map: metadata first, supplement with known pairs
    obsolete_map: dict = {}
    for sid, entry in rfc_meta.items():
        obs_by = entry.get('obsoleted_by')
        if obs_by:
            obs_id = f"rfc{obs_by}" if not str(obs_by).startswith('rfc') else str(obs_by)
            obsolete_map[sid] = obs_id
    for sid, obs_id in _KNOWN_OBSOLETE.items():
        if sid not in obsolete_map:
            obsolete_map[sid] = obs_id

    for old_sid, new_sid in obsolete_map.items():
        if old_sid in all_db_ids:
            n = db.mark_obsolete(old_sid, new_sid)
            if n > 0:
                total_marked += n
                print(f"  ✓ Marked {n} chunk(s) of {old_sid} as obsoleted by {new_sid}")

    if total_marked == 0:
        print("  (no obsolescence changes needed)")
    else:
        print(f"  → {total_marked} chunks marked obsolete in total")

    # 5. Update sync_state
    watermark = f"rfc_count={len(all_rfc_files)};ts={sync_ts}"
    db.update_sync_state(
        source_type='rfc',
        watermark=watermark,
        embed_model=EMBED_MODEL,
        embed_dim=EMBEDDING_DIM,
    )
    print(f"\n✓ sync_state updated for source_type='rfc'")

    # 6. Write corpus_manifest.json
    print("── Writing corpus_manifest.json ──────────────────────────────────────")
    manifest = build_corpus_manifest(db, rfc_meta, sync_ts)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"✓ corpus_manifest.json written ({manifest['rfc_count']} unique RFC source_ids)")
    print(f"  Total chunks: {manifest['total_chunks']:,}")
    print(f"  By source:    {manifest['by_source']}")

    total_elapsed = time.time() - t0
    print(f"\n✓ All done in {total_elapsed:.1f}s")


if __name__ == '__main__':
    main()
