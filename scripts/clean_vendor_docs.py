"""Normalize vendor docs (.rst / .md / .html) into plain text with uniform
Markdown-style '#' headings, so the chunker only has to understand one
heading convention regardless of source format.

Input:  data/vendor_docs/<product>/**/*.{rst,md,html}
Output: data/vendor_docs_clean/<product>/**/*.txt   (mirrors relative path)
"""
import os
import re
import html
from html.parser import HTMLParser

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(BASE, "data", "vendor_docs")
OUT_ROOT = os.path.join(BASE, "data", "vendor_docs_clean")


# ---------- RST ----------

UNDERLINE_CHARS = set("=-~^\"'`#*+.:_")
DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+[\w-]+::")
FIELD_RE = re.compile(r"^\s*:[\w-]+:.*$")
COMMENT_RE = re.compile(r"^\s*\.\.\s*(#.*)?$")


def clean_rst(text: str) -> str:
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else ""

        # Heading: text line followed by an underline of a single repeated symbol
        stripped = nxt.strip()
        if (
            line.strip()
            and stripped
            and len(set(stripped)) == 1
            and stripped[0] in UNDERLINE_CHARS
            and len(stripped) >= max(3, len(line.strip()) - 2)
        ):
            out.append("# " + line.strip())
            i += 2
            continue

        # Skip directives (images, toctree, etc.) and their indented body
        if DIRECTIVE_RE.match(line) or COMMENT_RE.match(line):
            i += 1
            while i < n and (lines[i].strip() == "" or lines[i].startswith((" ", "\t"))):
                if lines[i].strip() == "" and (i + 1 >= n or not lines[i + 1].startswith((" ", "\t"))):
                    break
                i += 1
            continue

        # Skip field lists (:align:, :alt:, ...)
        if FIELD_RE.match(line):
            i += 1
            continue

        out.append(line)
        i += 1

    result = "\n".join(out)
    # Strip common inline rst markup -> plain text
    result = re.sub(r":ref:`([^`<]+)(<[^>]+>)?`", r"\1", result)
    result = re.sub(r":doc:`([^`<]+)(<[^>]+>)?`", r"\1", result)
    result = re.sub(r"`([^`<]+)\s*<[^>]+>`_+", r"\1", result)  # `text <url>`_
    result = re.sub(r"``([^`]+)``", r"\1", result)
    result = re.sub(r"`([^`]+)`_+", r"\1", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() + "\n"


# ---------- Markdown ----------

FRONTMATTER_RE = re.compile(r"^\+\+\+\n.*?\n\+\+\+\n", re.DOTALL)
YAML_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def clean_md(text: str) -> str:
    text = FRONTMATTER_RE.sub("", text, count=1)
    text = YAML_FRONTMATTER_RE.sub("", text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# ---------- HTML ----------

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []
        self.skip_depth = 0
        self.heading_level = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_depth += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.heading_level = int(tag[1])
            self.out.append("\n" + "#" * self.heading_level + " ")
        elif tag in ("p", "div", "li", "br", "tr"):
            self.out.append("\n")
        elif tag in ("pre", "code"):
            self.out.append("\n```\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
        elif re.fullmatch(r"h[1-6]", tag):
            self.heading_level = None
            self.out.append("\n")
        elif tag in ("pre", "code"):
            self.out.append("\n```\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.out.append(data)


def clean_html(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    raw = "".join(parser.out)
    raw = html.unescape(raw)
    lines = [ln.rstrip() for ln in raw.split("\n")]
    result = "\n".join(lines)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() + "\n"


def main():
    converted = 0
    for dirpath, _dirs, filenames in os.walk(SRC_ROOT):
        for fname in filenames:
            src_path = os.path.join(dirpath, fname)
            rel = os.path.relpath(src_path, SRC_ROOT)
            ext = os.path.splitext(fname)[1].lower()
            with open(src_path, encoding="utf-8", errors="replace") as f:
                raw = f.read()

            if ext == ".rst":
                cleaned = clean_rst(raw)
            elif ext == ".md":
                cleaned = clean_md(raw)
            elif ext == ".html":
                cleaned = clean_html(raw)
            else:
                continue

            out_path = os.path.join(OUT_ROOT, os.path.splitext(rel)[0] + ".txt")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(cleaned)
            converted += 1

    print(f"Normalized {converted} vendor doc files -> {OUT_ROOT}")


if __name__ == "__main__":
    main()
