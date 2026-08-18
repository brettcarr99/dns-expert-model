"""Chunk cleaned mailing-list messages (data/discussions_clean/*.jsonl) into
a unified JSONL ready for embedding, with citation breadcrumbs.

Most messages are already short enough to be a single chunk; long ones are
split on paragraph boundaries the same way scripts/build_chunks.py does for
RFCs/vendor docs, with a small overlap for context continuity.

Output: data/chunks/discussions_chunks.jsonl (separate from chunks.jsonl /
chunks_enriched.jsonl -- this stage never touches the RFC/vendor pipeline).
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_DIR = os.path.join(BASE, "data", "discussions_clean")
OUT_PATH = os.path.join(BASE, "data", "chunks", "discussions_chunks.jsonl")

TARGET_CHARS = 1600
OVERLAP_CHARS = 200
MIN_CHARS = 80

LIST_DISPLAY_NAMES = {
    "ietf-dnsop": "IETF dnsop mailing list",
    "ietf-dns-privacy": "IETF dns-privacy mailing list",
    "ietf-dd": "IETF dd mailing list",
    "dns-oarc-dns-operations": "DNS-OARC dns-operations mailing list",
    "ripe-dns-wg": "RIPE DNS Working Group mailing list",
}


def split_long_body(text, target=TARGET_CHARS, overlap=OVERLAP_CHARS):
    import re
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []
    chunks = []
    cur = []
    cur_len = 0
    for p in paras:
        if cur_len + len(p) > target and cur:
            chunks.append("\n\n".join(cur))
            tail = chunks[-1][-overlap:]
            cur = [tail, p] if tail else [p]
            cur_len = len(tail) + len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return [c.strip() for c in chunks if len(c.strip()) >= MIN_CHARS]


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    records = []

    for fname in sorted(os.listdir(CLEAN_DIR)):
        if not fname.endswith(".jsonl"):
            continue
        list_name = fname[: -len(".jsonl")]
        display_name = LIST_DISPLAY_NAMES.get(list_name, list_name)
        with open(os.path.join(CLEAN_DIR, fname), encoding="utf-8") as f:
            messages = [json.loads(line) for line in f]

        for msg in messages:
            date = msg.get("date") or "undated"
            breadcrumb = (
                f"{display_name} — {date} — {msg['author']} — "
                f"Re: {msg['normalized_subject']}"
            )
            pieces = split_long_body(msg["body"])
            for idx, piece in enumerate(pieces):
                records.append({
                    "id": f"{msg['id']}#{idx}",
                    "text": f"{breadcrumb}\n\n{piece}",
                    "source_type": "discussion",
                    "list": list_name,
                    "date": msg.get("date"),
                    "author": msg["author"],
                    "subject": msg["subject"],
                    "normalized_subject": msg["normalized_subject"],
                })

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    by_list = Counter(r["list"] for r in records)
    print(f"Wrote {len(records)} chunks -> {OUT_PATH}")
    for list_name, count in by_list.most_common():
        print(f"  {list_name}: {count}")


if __name__ == "__main__":
    main()
