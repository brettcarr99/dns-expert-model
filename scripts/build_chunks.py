"""Section-aware chunking of cleaned RFCs + vendor docs into a unified JSONL
ready for embedding.

Each chunk record:
{
  "id": "rfc1035#3.3.9" | "bind9/arm/dnssec#Configuring-keys-0",
  "text": "<breadcrumb>\n\n<chunk text>",     # what actually gets embedded
  "source_type": "rfc" | "vendor",
  "product": "bind9" | null,                  # vendor only
  "rfc": 1035 | null,                         # rfc only
  "title": "DOMAIN NAMES - IMPLEMENTATION AND SPECIFICATION" | "dnssec.rst",
  "status": "INTERNET STANDARD" | null,        # rfc only
  "year": "1987" | null,                       # rfc only
  "section": "3.3.9. MX RDATA format" | "Configuring keys",
  "doc_path": "data/rfcs/clean/rfc1035.txt",
}

Output: data/chunks/chunks.jsonl
"""
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RFC_CLEAN_DIR = os.path.join(BASE, "data", "rfcs", "clean")
RFC_META_PATH = os.path.join(BASE, "data", "rfcs", "metadata", "dns_rfcs_filtered.json")
VENDOR_CLEAN_DIR = os.path.join(BASE, "data", "vendor_docs_clean")
OUT_PATH = os.path.join(BASE, "data", "chunks", "chunks.jsonl")

TARGET_CHARS = 1600
OVERLAP_CHARS = 200
MIN_CHARS = 80

RFC_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
MD_HEADING_RE = re.compile(r"^(#+)\s+(.*)$")


def split_long_section(text: str, target=TARGET_CHARS, overlap=OVERLAP_CHARS):
    """Split on paragraph boundaries, keeping pieces near `target` chars with overlap."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []
    chunks = []
    cur = []
    cur_len = 0
    for p in paras:
        if cur_len + len(p) > target and cur:
            chunks.append("\n\n".join(cur))
            # carry the tail of the previous chunk forward for overlap/context
            tail = chunks[-1][-overlap:]
            cur = [tail, p] if tail else [p]
            cur_len = len(tail) + len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return [c.strip() for c in chunks if len(c.strip()) >= MIN_CHARS]


def chunk_rfc(num, meta, text):
    lines = text.split("\n")
    sections = []  # list of (section_label, [lines])
    current_label = "Preamble"
    current_lines = []
    for line in lines:
        m = RFC_SECTION_RE.match(line.strip())
        if m:
            sections.append((current_label, current_lines))
            current_label = f"{m.group(1)}. {m.group(2)}"
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_label, current_lines))

    title = meta.get("title", "") if meta else ""
    breadcrumb_base = f"RFC {num} — {title}"

    records = []
    for label, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < MIN_CHARS:
            continue
        pieces = split_long_section(body)
        for idx, piece in enumerate(pieces):
            suffix = f"-{idx}" if len(pieces) > 1 else ""
            breadcrumb = f"{breadcrumb_base} > {label}"
            records.append({
                "id": f"rfc{num}#{label.split('.')[0]}{suffix}#{idx}",
                "text": f"{breadcrumb}\n\n{piece}",
                "source_type": "rfc",
                "product": None,
                "rfc": num,
                "title": title,
                "status": meta.get("status") if meta else None,
                "year": meta.get("year") if meta else None,
                "section": label,
                "doc_path": f"data/rfcs/clean/rfc{num}.txt",
            })
    return records


def chunk_vendor_doc(product, rel_path, text):
    lines = text.split("\n")
    sections = []
    heading_stack = []  # list of (level, text)
    current_lines = []

    def label_for_stack():
        return " > ".join(h[1] for h in heading_stack) if heading_stack else os.path.basename(rel_path)

    for line in lines:
        m = MD_HEADING_RE.match(line)
        if m:
            sections.append((label_for_stack(), current_lines))
            level = len(m.group(1))
            heading_stack = [h for h in heading_stack if h[0] < level]
            heading_stack.append((level, m.group(2).strip()))
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((label_for_stack(), current_lines))

    breadcrumb_base = f"{product} docs — {rel_path}"
    records = []
    for label, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < MIN_CHARS:
            continue
        pieces = split_long_section(body)
        for idx, piece in enumerate(pieces):
            breadcrumb = f"{breadcrumb_base} > {label}" if label else breadcrumb_base
            records.append({
                "id": f"{product}:{rel_path}#{label}#{idx}",
                "text": f"{breadcrumb}\n\n{piece}",
                "source_type": "vendor",
                "product": product,
                "rfc": None,
                "title": rel_path,
                "status": None,
                "year": None,
                "section": label,
                "doc_path": f"data/vendor_docs_clean/{product}/{rel_path}",
            })
    return records


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    with open(RFC_META_PATH) as f:
        rfc_meta_list = json.load(f)
    rfc_meta = {m["rfc"]: m for m in rfc_meta_list}

    all_records = []

    rfc_files = sorted(f for f in os.listdir(RFC_CLEAN_DIR) if f.endswith(".txt"))
    for fname in rfc_files:
        num = int(re.match(r"rfc(\d+)\.txt", fname).group(1))
        with open(os.path.join(RFC_CLEAN_DIR, fname), encoding="utf-8") as f:
            text = f.read()
        all_records.extend(chunk_rfc(num, rfc_meta.get(num), text))

    for dirpath, _dirs, filenames in os.walk(VENDOR_CLEAN_DIR):
        for fname in sorted(filenames):
            if not fname.endswith(".txt"):
                continue
            full_path = os.path.join(dirpath, fname)
            rel_to_vendor = os.path.relpath(full_path, VENDOR_CLEAN_DIR)
            product = rel_to_vendor.split(os.sep)[0]
            rel_path = os.path.relpath(full_path, os.path.join(VENDOR_CLEAN_DIR, product))
            with open(full_path, encoding="utf-8") as f:
                text = f.read()
            all_records.extend(chunk_vendor_doc(product, rel_path, text))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    rfc_count = sum(1 for r in all_records if r["source_type"] == "rfc")
    vendor_count = sum(1 for r in all_records if r["source_type"] == "vendor")
    print(f"Wrote {len(all_records)} chunks ({rfc_count} rfc, {vendor_count} vendor) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
