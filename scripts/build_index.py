"""Embed all chunks (via Ollama's nomic-embed-text) and store them in a local
LanceDB table so retrieval never needs a server process.

Input:  data/chunks/chunks_enriched.jsonl (falls back to chunks.jsonl if the
        enrichment step hasn't been run)
Output: data/index/dns_chunks.lance  (LanceDB table "chunks")
"""
import json
import os
import time

import lancedb
import ollama
import pyarrow as pa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNKS_PATH = os.path.join(BASE, "data", "chunks", "chunks_enriched.jsonl")
if not os.path.exists(CHUNKS_PATH):
    CHUNKS_PATH = os.path.join(BASE, "data", "chunks", "chunks.jsonl")
INDEX_DIR = os.path.join(BASE, "data", "index")

EMBED_MODEL = "nomic-embed-text"
BATCH_SIZE = 64


def embed_batch(client, texts):
    # nomic-embed-text expects a task prefix for best retrieval quality
    prefixed = [f"search_document: {t}" for t in texts]
    resp = client.embed(model=EMBED_MODEL, input=prefixed)
    return resp["embeddings"]


def main():
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    client = ollama.Client()

    # probe embedding dim
    dim = len(embed_batch(client, [records[0]["text"]])[0])
    print(f"Embedding dim: {dim}, chunks to embed: {len(records)}")

    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("product", pa.string()),
        pa.field("rfc", pa.int64()),
        pa.field("title", pa.string()),
        pa.field("status", pa.string()),
        pa.field("year", pa.string()),
        pa.field("section", pa.string()),
        pa.field("doc_path", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])

    db = lancedb.connect(INDEX_DIR)
    if "chunks" in db.table_names():
        db.drop_table("chunks")
    table = db.create_table("chunks", schema=schema)

    start = time.time()
    buffer = []
    total = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        vectors = embed_batch(client, [r["text"] for r in batch])
        for r, v in zip(batch, vectors):
            buffer.append({
                "id": r["id"],
                "text": r["text"],
                "source_type": r["source_type"],
                "product": r.get("product") or "",
                "rfc": r.get("rfc") or 0,
                "title": r.get("title") or "",
                "status": r.get("status") or "",
                "year": r.get("year") or "",
                "section": r.get("section") or "",
                "doc_path": r.get("doc_path") or "",
                "vector": v,
            })
        total += len(batch)
        if len(buffer) >= 500:
            table.add(buffer)
            buffer = []
        if total % 1000 < BATCH_SIZE:
            elapsed = time.time() - start
            rate = total / elapsed if elapsed else 0
            print(f"  {total}/{len(records)} embedded ({rate:.1f} chunks/s)")

    if buffer:
        table.add(buffer)

    print(f"Done in {time.time() - start:.1f}s.")
    # Deliberately NOT building an IVF_PQ ANN index: at ~12k rows brute-force
    # cosine search is fast (<1s) and exact. An ANN index was tried here
    # previously and it silently degraded recall badly -- e.g. a true nearest
    # neighbor at cosine distance 0.30 got ranked #219 instead of top-3
    # because IVF_PQ's product quantization is lossy and has too few rows per
    # partition to be accurate at this scale. Keep this brute-force.
    print(f"Indexed {table.count_rows()} chunks -> {INDEX_DIR}")


if __name__ == "__main__":
    main()
