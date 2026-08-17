"""Diagnostic: how common is the also-notify-style retrieval failure across
the whole corpus, not just the one eval case that happened to surface it?

Method: every "terse directive reference" chunk (the same ~1.2k population
`enrich_chunks.py` targets) already has a natural-language paraphrase of its
own content, generated during enrichment ("Also commonly asked as: ..."). Use
that paraphrase as a synthetic "how would a user ask this" query against the
PRE-enrichment baseline index, and check whether the chunk retrieves itself
in the top-K. This measures, corpus-wide, how often a terse directive chunk
fails to surface for a natural rephrasing of its own content -- i.e. whether
also-notify was a one-off or symptomatic of a broader pattern.

Uses the already-generated paraphrases (zero new LLM calls) against a
throwaway baseline index built by this session at /tmp/dns_expert_baseline_index
(pre-enrichment embeddings, so this measures the *original* problem, not the
already-improved current index).

Output: prints overall hit rate + per-product breakdown + a sample of misses.
"""
import json
import os
import re

import lancedb
import ollama

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_PATH = os.path.join(BASE, "data", "chunks", "chunks_enriched.jsonl")
BASELINE_INDEX_DIR = "/tmp/dns_expert_baseline_index"
EMBED_MODEL = "nomic-embed-text"
TOP_K = 8
MAX_BODY_CHARS = 700
SECTION_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{1,40}")


def is_candidate(rec):
    if rec["source_type"] != "vendor":
        return False
    section = (rec["section"] or "").strip()
    last = section.split(">")[-1].strip() if section else ""
    # length check against the ORIGINAL body (pre-enrichment length proxy):
    # enriched text has the paraphrase line added, so subtract a generous
    # allowance rather than re-reading the original file.
    return bool(SECTION_TOKEN_RE.fullmatch(last)) and len(rec["text"]) < MAX_BODY_CHARS + 250


def extract_paraphrase(enriched_text):
    m = re.search(r"^Also commonly asked as: (.+)$", enriched_text, re.MULTILINE)
    return m.group(1).strip() if m else None


def main():
    with open(ENRICHED_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    candidates = []
    for r in records:
        if not is_candidate(r):
            continue
        para = extract_paraphrase(r["text"])
        if para:
            candidates.append((r, para))

    print(f"{len(candidates)} candidates with a paraphrase to test")

    db = lancedb.connect(BASELINE_INDEX_DIR)
    table = db.open_table("chunks")
    client = ollama.Client()

    misses = []
    hits = 0
    for i, (rec, para) in enumerate(candidates, 1):
        qv = client.embed(model=EMBED_MODEL, input=[f"search_query: {para}"])["embeddings"][0]
        results = table.search(qv, vector_column_name="vector").metric("cosine").limit(TOP_K).to_list()
        found = any(r["id"] == rec["id"] for r in results)
        if found:
            hits += 1
        else:
            misses.append((rec, para))
        if i % 200 == 0:
            print(f"  {i}/{len(candidates)} tested, {hits} hits so far ({hits/i*100:.1f}%)")

    n = len(candidates)
    print(f"\nOverall: {hits}/{n} terse-chunk paraphrases self-retrieve in top-{TOP_K} "
          f"({hits/n*100:.1f}% hit rate, {len(misses)} misses, {len(misses)/n*100:.1f}% miss rate)")

    from collections import Counter
    miss_by_product = Counter(rec["product"] for rec, _ in misses)
    total_by_product = Counter(rec["product"] for rec, _ in candidates)
    print("\nMiss rate by product:")
    for product, total in sorted(total_by_product.items(), key=lambda x: -x[1]):
        m = miss_by_product.get(product, 0)
        print(f"  {product}: {m}/{total} missed ({m/total*100:.1f}%)")

    print(f"\nSample of {min(15, len(misses))} misses (id | paraphrase used as query):")
    for rec, para in misses[:15]:
        print(f"  {rec['id']}")
        print(f"    query: {para}")


if __name__ == "__main__":
    main()
