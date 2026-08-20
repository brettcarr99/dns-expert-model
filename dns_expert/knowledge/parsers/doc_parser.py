"""Vendor Documentation Parser supporting RST, Markdown, and HTML."""

import html
import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class DocParser:
    def __init__(self, vendor_docs_dir: Path):
        self.docs_dir = Path(vendor_docs_dir)

    def parse_all(self) -> Generator[Dict[str, Any], None, None]:
        if not self.docs_dir.exists():
            return

        for vendor_path in sorted(self.docs_dir.iterdir()):
            if vendor_path.is_dir():
                vendor_name = vendor_path.name.lower()
                for doc_file in vendor_path.rglob("*"):
                    if doc_file.is_file() and doc_file.suffix in [".rst", ".md", ".txt", ".html"]:
                        yield from self.parse_file(doc_file, vendor_name)

    def parse_file(self, file_path: Path, vendor: str) -> List[Dict[str, Any]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            return []

        rel_path = str(file_path.relative_to(self.docs_dir))
        doc_title = file_path.stem.replace("_", " ").replace("-", " ").title()

        if file_path.suffix == ".html":
            text = self._clean_html(text)
        elif file_path.suffix == ".rst":
            text = self._clean_rst(text)

        header_pattern = re.compile(r"(?:^|\n)(#{1,4}\s+[^\n]+|[A-Z][^\n]{3,60}\n[-=~`^]{3,60})", re.MULTILINE)
        splits = list(header_pattern.finditer(text))

        chunks = []
        if not splits:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            cur_chunk = []
            cur_len = 0
            for p in paragraphs:
                cur_chunk.append(p)
                cur_len += len(p)
                if cur_len > 1800:
                    content = "\n\n".join(cur_chunk)
                    chunks.append(self._create_chunk(vendor, doc_title, "General", content, rel_path))
                    cur_chunk = []
                    cur_len = 0
            if cur_chunk:
                content = "\n\n".join(cur_chunk)
                chunks.append(self._create_chunk(vendor, doc_title, "General", content, rel_path))
            return chunks

        for i in range(len(splits)):
            start_pos = splits[i].start()
            end_pos = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            section_header = splits[i].group(1).strip().replace("\n", " ")
            section_header = re.sub(r"^[#\-=\s]+", "", section_header).strip()
            section_body = text[start_pos:end_pos].strip()

            if len(section_body) > 3500:
                sub_paragraphs = [p.strip() for p in section_body.split("\n\n") if p.strip()]
                sub_chunk = []
                sub_len = 0
                sub_idx = 1
                for sp in sub_paragraphs:
                    sub_chunk.append(sp)
                    sub_len += len(sp)
                    if sub_len > 2000:
                        part_content = "\n\n".join(sub_chunk)
                        sec_name = f"{section_header} (Part {sub_idx})"
                        chunks.append(self._create_chunk(vendor, doc_title, sec_name, part_content, rel_path))
                        sub_chunk = []
                        sub_len = 0
                        sub_idx += 1
                if sub_chunk:
                    part_content = "\n\n".join(sub_chunk)
                    sec_name = f"{section_header} (Part {sub_idx})" if sub_idx > 1 else section_header
                    chunks.append(self._create_chunk(vendor, doc_title, sec_name, part_content, rel_path))
            else:
                chunks.append(self._create_chunk(vendor, doc_title, section_header, section_body, rel_path))

        return chunks

    def _clean_rst(self, text: str) -> str:
        text = re.sub(r"\.\.\s+(?:code-block|sourcecode)::\s*(\w+)?\n", r"```\1\n", text)
        text = re.sub(r"::\n", r"```\n", text)
        text = re.sub(r"\.\.\s+[a-zA-Z0-9_-]+::[^\n]*\n", "", text)
        text = re.sub(r":[a-zA-Z0-9_-]+:`([^`]+)`", r"\1", text)
        return text

    def _clean_html(self, text: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return html.unescape(text)

    def _create_chunk(
        self, vendor: str, doc_title: str, section: str, body: str, rel_path: str
    ) -> Dict[str, Any]:
        header_prefix = f"[Vendor Doc: {vendor.upper()} | Document: {doc_title} | Section: {section}]\n\n"
        full_content = header_prefix + body
        return {
            "source_type": "vendor_doc",
            "source_id": f"{vendor}/{rel_path}",
            "title": f"{vendor.upper()} - {doc_title}",
            "section": section,
            "vendor": vendor,
            "date": None,
            "url_or_path": rel_path,
            "content": full_content,
        }
