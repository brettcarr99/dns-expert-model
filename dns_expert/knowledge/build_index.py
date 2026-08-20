"""Knowledge Base Indexer: Parses RFCs, Docs, and Discussions into SQLite-vec DB."""

import argparse
import sys
import time
from pathlib import Path
from typing import List

from dns_expert.config import DB_PATH, DEFAULT_WORKSPACE_ROOT, EMBED_MODEL
from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.knowledge.parsers.doc_parser import DocParser
from dns_expert.knowledge.parsers.mail_parser import MailParser
from dns_expert.knowledge.parsers.rfc_parser import RFCParser
from dns_expert.ollama_client import OllamaClient


def build_knowledge_base(
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    db_path: Path = DB_PATH,
    skip_rfcs: bool = False,
    skip_docs: bool = False,
    skip_discussions: bool = False,
    skip_embeddings: bool = False,
    limit_discussions: int = 2000,
    batch_size: int = 16,
) -> None:
    workspace_root = Path(workspace_root)
    db = KnowledgeDB(db_path)
    client = OllamaClient(embed_model=EMBED_MODEL)

    print(f"[*] Starting Knowledge Base build...")
    print(f"[*] Target Database: {db.db_path}")
    print(f"[*] Workspace Root:  {workspace_root}")

    if not skip_embeddings:
        print(f"[*] Verifying Ollama embedding model: {EMBED_MODEL}...")
        try:
            test_emb = client.get_embedding("DNS Root Zone")
            print(f"[+] Embedding model active! Vector dimension: {len(test_emb)}")
        except Exception as e:
            print(f"[!] Warning: Embedding generation failed ({e}). Proceeding in text-only mode.")
            skip_embeddings = True

    start_time = time.time()
    total_inserted = 0

    # 1. Index RFCs
    if not skip_rfcs:
        rfc_dir = workspace_root / "rfcs" / "clean"
        meta_file = workspace_root / "rfcs" / "metadata" / "dns_rfcs_filtered.json"
        print(f"\n[*] Parsing DNS RFCs from {rfc_dir}...")
        parser = RFCParser(rfc_dir, meta_file)
        rfc_chunks = list(parser.parse_all())
        print(f"[+] Generated {len(rfc_chunks)} RFC section chunks.")

        inserted = _process_and_insert(db, client, rfc_chunks, skip_embeddings, batch_size, "RFCs")
        total_inserted += inserted

    # 2. Index Vendor Docs
    if not skip_docs:
        docs_dir = workspace_root / "vendor_docs"
        print(f"\n[*] Parsing Vendor Documentation from {docs_dir}...")
        doc_parser = DocParser(docs_dir)
        doc_chunks = list(doc_parser.parse_all())
        print(f"[+] Generated {len(doc_chunks)} Vendor Doc chunks.")

        inserted = _process_and_insert(db, client, doc_chunks, skip_embeddings, batch_size, "Vendor Docs")
        total_inserted += inserted

    # 3. Index Discussions (Mailing Lists)
    if not skip_discussions:
        disc_dir = workspace_root / "discussions"
        print(f"\n[*] Parsing Mailing List Discussions from {disc_dir} (limit={limit_discussions})...")
        mail_parser = MailParser(disc_dir)
        mail_chunks = []
        for ch in mail_parser.parse_all(max_per_list=limit_discussions // 3 if limit_discussions else None):
            mail_chunks.append(ch)
            if limit_discussions and len(mail_chunks) >= limit_discussions:
                break
        print(f"[+] Generated {len(mail_chunks)} Discussion chunks.")

        inserted = _process_and_insert(db, client, mail_chunks, skip_embeddings, batch_size, "Discussions")
        total_inserted += inserted

    elapsed = time.time() - start_time
    stats = db.get_stats()
    print(f"\n[+] Indexing Complete in {elapsed:.1f}s!")
    print(f"    - Total Indexed Chunks: {stats['total_chunks']}")
    print(f"    - Chunks with Vectors:  {stats['chunks_with_embeddings']}")
    print(f"    - Source Breakdown:     {stats['by_source']}")
    print(f"    - Database Size:        {stats['size_mb']} MB")


def _process_and_insert(
    db: KnowledgeDB,
    client: OllamaClient,
    chunks: List[dict],
    skip_embeddings: bool,
    batch_size: int,
    label: str,
) -> int:
    if not chunks:
        return 0

    print(f"[*] Embedding and storing {len(chunks)} {label} chunks...")
    batch = []
    inserted_count = 0

    for i, chunk in enumerate(chunks):
        if not skip_embeddings:
            try:
                emb = client.get_embedding(chunk["content"][:2000])
                chunk["embedding"] = emb
            except Exception:
                chunk["embedding"] = None

        batch.append(chunk)

        if len(batch) >= batch_size:
            db.insert_chunks_batch(batch)
            inserted_count += len(batch)
            batch = []
            sys.stdout.write(f"\r    -> Processed {inserted_count}/{len(chunks)} {label}...")
            sys.stdout.flush()

    if batch:
        db.insert_chunks_batch(batch)
        inserted_count += len(batch)
        sys.stdout.write(f"\r    -> Processed {inserted_count}/{len(chunks)} {label}... Done!\n")
        sys.stdout.flush()

    return inserted_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DNS-Expert Knowledge Base Builder")
    parser.add_argument("--workspace", type=str, default=str(DEFAULT_WORKSPACE_ROOT), help="Workspace root directory")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Output SQLite database path")
    parser.add_argument("--skip-rfcs", action="store_true", help="Skip RFC indexing")
    parser.add_argument("--skip-docs", action="store_true", help="Skip Vendor Doc indexing")
    parser.add_argument("--skip-discussions", action="store_true", help="Skip Mailing List indexing")
    parser.add_argument("--no-embeddings", action="store_true", help="Skip vector embedding generation (text only)")
    parser.add_argument("--limit-discussions", type=int, default=1500, help="Max discussion messages to index")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch insertion size")

    args = parser.parse_args()

    build_knowledge_base(
        workspace_root=Path(args.workspace),
        db_path=Path(args.db),
        skip_rfcs=args.skip_rfcs,
        skip_docs=args.skip_docs,
        skip_discussions=args.skip_discussions,
        skip_embeddings=args.no_embeddings,
        limit_discussions=args.limit_discussions,
        batch_size=args.batch_size,
    )
