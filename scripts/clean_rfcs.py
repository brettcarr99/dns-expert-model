"""Strip RFC-editor pagination boilerplate (form feeds, running headers/footers)
from raw RFC text files, while preserving the actual document structure
(section numbers/titles, examples, ABNF, etc).

Input:  data/rfcs/raw/rfcNNNN.txt
Output: data/rfcs/clean/rfcNNNN.txt
"""
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "rfcs", "raw")
CLEAN_DIR = os.path.join(BASE, "data", "rfcs", "clean")

FF = "\x0c"

# Running header, e.g.: "RFC 1035        Domain Implementation and Specification    November 1987"
HEADER_RE = re.compile(r"^\s*(RFC|Internet-Draft)\s+\S.*\d{4}\s*$", re.IGNORECASE)
# Running footer, e.g.: "Mockapetris                                                     [Page 2]"
FOOTER_RE = re.compile(r"^\s*\S.*\[Page\s+\d+\]\s*$")


def clean_text(raw: str) -> str:
    pages = raw.split(FF)
    cleaned_pages = []
    for page in pages:
        lines = page.split("\n")
        # Drop leading blank lines, then one running-header line if present
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i < len(lines) and HEADER_RE.match(lines[i]):
            i += 1
            # header is usually followed by a couple blank lines
            while i < len(lines) and lines[i].strip() == "":
                i += 1
        # Drop trailing blank lines, then one running-footer line if present
        j = len(lines)
        while j > i and lines[j - 1].strip() == "":
            j -= 1
        if j > i and FOOTER_RE.match(lines[j - 1]):
            j -= 1
            while j > i and lines[j - 1].strip() == "":
                j -= 1
        cleaned_pages.append("\n".join(lines[i:j]))

    text = "\n\n".join(p for p in cleaned_pages if p.strip())
    # Collapse 3+ blank lines down to 2 (page-boundary artifacts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main():
    os.makedirs(CLEAN_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".txt"))
    for fname in files:
        with open(os.path.join(RAW_DIR, fname), encoding="utf-8", errors="replace") as f:
            raw = f.read()
        cleaned = clean_text(raw)
        with open(os.path.join(CLEAN_DIR, fname), "w", encoding="utf-8") as f:
            f.write(cleaned)
    print(f"Cleaned {len(files)} RFCs -> {CLEAN_DIR}")


if __name__ == "__main__":
    main()
