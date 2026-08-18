"""Embed discussion chunks (via Ollama's nomic-embed-text) and store them in
a *separate* local LanceDB table, so the RFC/vendor index (data/index/) is
never touched by this stage -- fully reversible by deleting data/index_discussions/.

Input:  data/chunks/discussions_chunks.jsonl
Output: data/index_discussions/  (LanceDB table "chunks")
"""
import json
import os
import time

import lancedb
import ollama
import pyarrow as pa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNKS_PATH = os.path.join(BASE, "data", "chunks", "discussions_chunks.jsonl")
INDEX_DIR = os.path.join(BASE, "data", "index_discussions")

EMBED_MODEL = "nomic-embed-text"
BATCH_SIZE = 64


def embed_batch(client, texts):
    prefixed = [f"search_document: {t}" for t in texts]
    resp = client.embed(model=EMBED_MODEL, input=prefixed)
    return resp["embeddings"]


def main():
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    client = ollama.Client()

    dim = len(embed_batch(client, [records[0]["text"]])[0])
    print(f"Embedding dim: {dim}, chunks to embed: {len(records)}")

    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("list", pa.string()),
        pa.field("date", pa.string()),
        pa.field("author", pa.string()),
        pa.field("subject", pa.string()),
        pa.field("normalized_subject", pa.string()),
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
                "list": r.get("list") or "",
                "date": r.get("date") or "",
                "author": r.get("author") or "",
                "subject": r.get("subject") or "",
                "normalized_subject": r.get("normalized_subject") or "",
                "vector": v,
            })
        total += len(batch)
        if len(buffer) >= 500:
            table.add(buffer)
            buffer = []
        if total % 2000 < BATCH_SIZE:
            elapsed = time.time() - start
            rate = total / elapsed if elapsed else 0
            print(f"  {total}/{len(records)} embedded ({rate:.1f} chunks/s)")

    if buffer:
        table.add(buffer)

    # Deliberately no ANN index -- brute-force cosine search is exact and,
    # at this scale, plenty fast. See README "Known limitations" for why
    # an ANN index degraded retrieval badly in the RFC/vendor index.
    print(f"Done in {time.time() - start:.1f}s. Indexed {table.count_rows()} chunks -> {INDEX_DIR}")


if __name__ == "__main__":
    main()
