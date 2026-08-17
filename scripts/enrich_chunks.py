"""Enrich short, terse vendor-doc chunks (config directive references etc.)
with a one-sentence natural-language paraphrase, generated locally, so their
embeddings align better with how users actually phrase questions.

Rationale: a chunk whose body is just "also-notify: When notifying a zone,
also notify these nameservers..." embeds close to other terse directive
docs, but can rank poorly against a paraphrased question like "what setting
sends NOTIFY to additional nameservers". Appending a synthetic paraphrase
closes that gap without touching the underlying facts.

Input:  data/chunks/chunks.jsonl
Output: data/chunks/chunks_enriched.jsonl (all records; only candidates get
        a paraphrase line inserted into `text`)
"""
import json
import os
import re
import time

import ollama

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_PATH = os.path.join(BASE, "data", "chunks", "chunks.jsonl")
OUT_PATH = os.path.join(BASE, "data", "chunks", "chunks_enriched.jsonl")

MODEL = "lfm2.5:8b-a1b-q4_K_M"
MAX_BODY_CHARS = 700
SECTION_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{1,40}")

PROMPT_TEMPLATE = """Given a short excerpt from {product} DNS server documentation, write ONE
short sentence (max 20 words) that paraphrases what it covers, using
different wording someone might naturally search with. Do not add facts
that aren't in the excerpt, and don't just repeat the excerpt's wording.
Output only the sentence, nothing else. /no_think

Excerpt (section "{section}"):
{body}

Sentence:"""


def is_candidate(rec):
    if rec["source_type"] != "vendor":
        return False
    section = (rec["section"] or "").strip()
    last = section.split(">")[-1].strip() if section else ""
    return bool(SECTION_TOKEN_RE.fullmatch(last)) and len(rec["text"]) < MAX_BODY_CHARS


def enrich(client, rec):
    section = (rec["section"] or "").strip().split(">")[-1].strip()
    body = rec["text"]
    prompt = PROMPT_TEMPLATE.format(product=rec["product"], section=section, body=body)
    resp = client.chat(model=MODEL, messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.3})
    sentence = resp["message"]["content"].strip().strip('"')
    if not sentence or len(sentence) > 300:
        return rec  # bad/empty generation, skip enrichment for this chunk
    breadcrumb, _, body_text = rec["text"].partition("\n\n")
    new_text = f"{breadcrumb}\nAlso commonly asked as: {sentence}\n\n{body_text}"
    return {**rec, "text": new_text}


def main():
    with open(IN_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    client = ollama.Client()
    candidates = [r for r in records if is_candidate(r)]
    print(f"{len(records)} total chunks, {len(candidates)} candidates for enrichment")

    out = []
    start = time.time()
    done_candidates = 0
    for rec in records:
        if is_candidate(rec):
            try:
                rec = enrich(client, rec)
            except Exception as e:
                print(f"  FAILED {rec['id']}: {e}")
            done_candidates += 1
            if done_candidates % 50 == 0:
                elapsed = time.time() - start
                rate = done_candidates / elapsed
                eta = (len(candidates) - done_candidates) / rate if rate else 0
                print(f"  {done_candidates}/{len(candidates)} enriched "
                      f"({rate:.2f}/s, eta {eta/60:.1f} min)")
        out.append(rec)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Done in {(time.time()-start)/60:.1f} min. Wrote {len(out)} records -> {OUT_PATH}")


if __name__ == "__main__":
    main()
