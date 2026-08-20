"""RFC Document Parser and Section-Aware Chunker."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class RFCParser:
    def __init__(self, rfc_dir: Path, metadata_path: Optional[Path] = None):
        self.rfc_dir = Path(rfc_dir)
        self.metadata_path = Path(metadata_path) if metadata_path else None
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        meta_map = {}
        if self.metadata_path and self.metadata_path.exists():
            try:
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        rfc_num = str(item.get("rfc", ""))
                        if rfc_num:
                            meta_map[rfc_num] = item
            except Exception:
                pass
        return meta_map

    def parse_all(self) -> Generator[Dict[str, Any], None, None]:
        if not self.rfc_dir.exists():
            return

        for rfc_file in sorted(self.rfc_dir.glob("rfc*.txt")):
            yield from self.parse_file(rfc_file)

    def parse_file(self, file_path: Path) -> List[Dict[str, Any]]:
        match = re.search(r'rfc(\d+)', file_path.name, re.IGNORECASE)
        if not match:
            return []

        rfc_num = match.group(1)
        meta = self.metadata.get(rfc_num, {})
        status = meta.get("status", "UNKNOWN")
        year = meta.get("year", "")

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception:
            return []

        title = meta.get("title")
        if not title:
            title = self._extract_title_from_text(text, rfc_num)

        section_pattern = re.compile(
            r'(?:^|\n\n)((?:[0-9]+\.(?:[0-9]+\.)*\s+[A-Z][^\n]+)|(?:[A-Z][A-Za-z0-9\s-]{3,40}\n[-=]{3,40})|(?:(?:Abstract|Status of this Memo|Table of Contents|Security Considerations|IANA Considerations|References|Authors?\x27? Addresses?)\b[^\n]*))',
            re.MULTILINE
        )

        splits = list(section_pattern.finditer(text))
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
                    chunks.append(self._create_chunk(rfc_num, title, status, year, "General", content, file_path))
                    cur_chunk = []
                    cur_len = 0
            if cur_chunk:
                content = "\n\n".join(cur_chunk)
                chunks.append(self._create_chunk(rfc_num, title, status, year, "General", content, file_path))
            return chunks

        for i in range(len(splits)):
            start_pos = splits[i].start()
            end_pos = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            section_header = splits[i].group(1).strip().replace("\n", " ")
            section_body = text[start_pos:end_pos].strip()

            if "Table of Contents" in section_header and len(section_body) < 3000:
                continue

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
                        chunks.append(self._create_chunk(rfc_num, title, status, year, sec_name, part_content, file_path))
                        sub_chunk = []
                        sub_len = 0
                        sub_idx += 1
                if sub_chunk:
                    part_content = "\n\n".join(sub_chunk)
                    sec_name = f"{section_header} (Part {sub_idx})" if sub_idx > 1 else section_header
                    chunks.append(self._create_chunk(rfc_num, title, status, year, sec_name, part_content, file_path))
            else:
                chunks.append(self._create_chunk(rfc_num, title, status, year, section_header, section_body, file_path))

        return chunks

    def _extract_title_from_text(self, text: str, rfc_num: str) -> str:
        # Look for text block immediately preceding Abstract or Status of this Memo
        abstract_match = re.search(r'\n\n([^\n]+(?:\n[^\n]+)?)\n\n+(?:Abstract|Status of this Memo)', text[:3000], re.IGNORECASE)
        if abstract_match:
            cand = abstract_match.group(1).strip().replace('\n', ' ')
            if len(cand) > 3 and "Request for Comments" not in cand:
                return cand
        return f"RFC {rfc_num}"

    def _create_chunk(
        self, rfc_num: str, title: str, status: str, year: str, section: str, body: str, file_path: Path
    ) -> Dict[str, Any]:
        header_prefix = f"[RFC {rfc_num}: {title} (Status: {status}, Year: {year}) | Section: {section}]\n\n"
        full_content = header_prefix + body
        return {
            "source_type": "rfc",
            "source_id": f"rfc{rfc_num}",
            "title": f"RFC {rfc_num}: {title}",
            "section": section,
            "vendor": None,
            "date": str(year),
            "url_or_path": str(file_path),
            "content": full_content,
        }
