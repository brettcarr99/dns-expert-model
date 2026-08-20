"""Mailing List Discussion Parser for EML files and compressed archives."""

import email
import email.policy
import gzip
import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class MailParser:
    def __init__(self, discussions_dir: Path):
        self.disc_dir = Path(discussions_dir)

    def parse_all(self, max_per_list: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        if not self.disc_dir.exists():
            return

        for org_dir in sorted(self.disc_dir.iterdir()):
            if org_dir.is_dir():
                org_name = org_dir.name.lower()
                for list_dir in sorted(org_dir.iterdir()):
                    if list_dir.is_dir():
                        list_name = f"{org_name}/{list_dir.name.lower()}"
                        yield from self.parse_list_directory(list_dir, list_name, max_count=max_per_list)

    def parse_list_directory(
        self, list_dir: Path, list_name: str, max_count: Optional[int] = None
    ) -> Generator[Dict[str, Any], None, None]:
        count = 0

        # Process .eml files
        for eml_file in sorted(list_dir.glob("*.eml")):
            chunks = self.parse_eml_file(eml_file, list_name)
            for c in chunks:
                yield c
                count += 1
                if max_count and count >= max_count:
                    return

        # Process .txt.gz archives
        for gz_file in sorted(list_dir.glob("*.txt.gz")):
            chunks = self.parse_gz_archive(gz_file, list_name)
            for c in chunks:
                yield c
                count += 1
                if max_count and count >= max_count:
                    return

    def parse_eml_file(self, file_path: Path, list_name: str) -> List[Dict[str, Any]]:
        try:
            with open(file_path, "rb") as f:
                msg = email.message_from_binary_file(f, policy=email.policy.default)
        except Exception:
            return []

        subject = str(msg.get("Subject", "No Subject")).strip()
        from_hdr = str(msg.get("From", "Unknown")).strip()
        date_hdr = str(msg.get("Date", "")).strip()
        msg_id = str(msg.get("Message-ID", file_path.name)).strip()

        if self._is_ignorable(subject, from_hdr):
            return []

        body = self._extract_body(msg)
        cleaned_body = self._clean_mail_body(body)

        if len(cleaned_body.strip()) < 50:
            return []

        rel_path = str(file_path.relative_to(self.disc_dir))
        return self._chunk_message(list_name, subject, from_hdr, date_hdr, msg_id, cleaned_body, rel_path)

    def parse_gz_archive(self, file_path: Path, list_name: str) -> List[Dict[str, Any]]:
        chunks = []
        try:
            with gzip.open(file_path, "rt", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return []

        messages = re.split(r"\n(?=From\s+[^\n]+)", content)
        rel_path = str(file_path.relative_to(self.disc_dir))

        for idx, raw_msg in enumerate(messages):
            if not raw_msg.strip():
                continue
            try:
                msg = email.message_from_string(raw_msg, policy=email.policy.default)
                subject = str(msg.get("Subject", "No Subject")).strip()
                from_hdr = str(msg.get("From", "Unknown")).strip()
                date_hdr = str(msg.get("Date", "")).strip()
                msg_id = f"{file_path.stem}_{idx}"

                if self._is_ignorable(subject, from_hdr):
                    continue

                body = self._extract_body(msg)
                cleaned_body = self._clean_mail_body(body)

                if len(cleaned_body.strip()) < 60:
                    continue

                chunks.extend(
                    self._chunk_message(list_name, subject, from_hdr, date_hdr, msg_id, cleaned_body, rel_path)
                )
            except Exception:
                continue

        return chunks

    def _extract_body(self, msg: email.message.Message) -> str:
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition", ""))
                if ctype == "text/plain" and "attachment" not in cdispo:
                    try:
                        content = part.get_content()
                        if isinstance(content, str):
                            body_parts.append(content)
                    except Exception:
                        pass
        else:
            try:
                content = msg.get_content()
                if isinstance(content, str):
                    body_parts.append(content)
                elif isinstance(content, bytes):
                    body_parts.append(content.decode("utf-8", errors="ignore"))
            except Exception:
                pass

        return "\n".join(body_parts)

    def _clean_mail_body(self, body: str) -> str:
        body = re.sub(r"-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----", "", body, flags=re.DOTALL)
        body = re.sub(r"-----BEGIN PGP SIGNED MESSAGE-----.*?Hash:.*?\n\n", "", body, flags=re.DOTALL)

        lines = body.splitlines()
        filtered_lines = []
        consecutive_quotes = 0

        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith(">"):
                consecutive_quotes += 1
                if consecutive_quotes <= 3:
                    filtered_lines.append(line)
            else:
                consecutive_quotes = 0
                if re.search(r"(?:Unsubscribe|mailing list|listinfo|dns-operations@lists\.dns-oarc|dnsop@ietf)", trimmed, re.I):
                    continue
                filtered_lines.append(line)

        return "\n".join(filtered_lines).strip()

    def _is_ignorable(self, subject: str, from_hdr: str) -> bool:
        sub_lower = subject.lower()
        if any(w in sub_lower for w in ["out of office", "automatic reply", "auto-reply", "autoreply", "undelivered"]):
            return True
        if "mailer-daemon" in from_hdr.lower():
            return True
        return False

    def _chunk_message(
        self,
        list_name: str,
        subject: str,
        from_hdr: str,
        date_hdr: str,
        msg_id: str,
        body: str,
        rel_path: str,
    ) -> List[Dict[str, Any]]:
        header_prefix = (
            f"[Mailing List: {list_name.upper()} | Date: {date_hdr} | Author: {from_hdr} | Subject: {subject}]\n\n"
        )

        chunks = []
        if len(body) > 3000:
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
            cur_chunk = []
            cur_len = 0
            part_idx = 1
            for p in paragraphs:
                cur_chunk.append(p)
                cur_len += len(p)
                if cur_len > 1800:
                    content = header_prefix + "\n\n".join(cur_chunk)
                    chunks.append({
                        "source_type": "discussion",
                        "source_id": f"{list_name}/{msg_id}_p{part_idx}",
                        "title": f"[{list_name}] {subject}",
                        "section": f"Message Thread Part {part_idx}",
                        "vendor": None,
                        "date": date_hdr,
                        "url_or_path": rel_path,
                        "content": content,
                    })
                    cur_chunk = []
                    cur_len = 0
                    part_idx += 1
            if cur_chunk:
                content = header_prefix + "\n\n".join(cur_chunk)
                chunks.append({
                    "source_type": "discussion",
                    "source_id": f"{list_name}/{msg_id}_p{part_idx}",
                    "title": f"[{list_name}] {subject}",
                    "section": f"Message Thread Part {part_idx}",
                    "vendor": None,
                    "date": date_hdr,
                    "url_or_path": rel_path,
                    "content": content,
                })
        else:
            full_content = header_prefix + body
            chunks.append({
                "source_type": "discussion",
                "source_id": f"{list_name}/{msg_id}",
                "title": f"[{list_name}] {subject}",
                "section": "Discussion Thread",
                "vendor": None,
                "date": date_hdr,
                "url_or_path": rel_path,
                "content": full_content,
            })

        return chunks
