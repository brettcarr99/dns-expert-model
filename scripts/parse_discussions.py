"""Parse raw mailing-list archives (.eml files + .mbox.gz) into a unified,
cleaned JSONL format per list, with noise filtering applied inline.

Sources are never modified. Output goes to data/discussions_clean/ (new,
separate from every other pipeline stage's output) so this stage is fully
reversible: delete that directory and nothing else in the project is
affected.

Cleaning per message:
  - Prefer text/plain body; fall back to a simple HTML tag strip.
  - Strip quoted-reply lines ("> ..."), "On <date>, X wrote:" attribution
    lines, RFC 3676 signature blocks (-- delimiter), and mailing-list
    footer boilerplate (mailman's "____" separator and everything after).
  - Normalize the subject (strip Re:/Fwd:/[listname] prefixes) for
    citation and lightweight thread grouping.

Noise filtering (dropped, not written):
  - Body shorter than MIN_BODY_CHARS after cleaning (empty acks, "+1").
  - Subject/From matching known automated-bot patterns (New Version
    Notification, I-D Action, WG Action, Document Action) -- these are
    templated metadata, not discussion content.

Output: data/discussions_clean/<list>.jsonl
"""
import email
import email.header
import email.utils
import gzip
import json
import mailbox
import os
import re
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISCUSSIONS_DIR = os.path.join(BASE, "data", "discussions")
OUT_DIR = os.path.join(BASE, "data", "discussions_clean")

LIST_SOURCES = [
    ("ietf-dnsop", os.path.join(DISCUSSIONS_DIR, "ietf", "dnsop"), "eml"),
    ("ietf-dns-privacy", os.path.join(DISCUSSIONS_DIR, "ietf", "dns-privacy"), "eml"),
    ("ietf-dd", os.path.join(DISCUSSIONS_DIR, "ietf", "dd"), "eml"),
    ("dns-oarc-dns-operations", os.path.join(DISCUSSIONS_DIR, "dns-oarc", "dns-operations"), "mbox_gz"),
    ("ripe-dns-wg", os.path.join(DISCUSSIONS_DIR, "ripe", "dns-wg"), "mbox_gz"),
]

MIN_BODY_CHARS = 150

QUOTE_LINE_RE = re.compile(r"^\s*>")
ATTRIBUTION_RE = re.compile(
    r"^(On .{0,80}wrote:|Le .{0,80}écrit\s*:|-{2,}\s*Original Message\s*-{2,}|From:\s.*)\s*$",
    re.IGNORECASE,
)
FOOTER_SEP_RE = re.compile(r"^_{10,}\s*$")
SIG_DELIM_RE = re.compile(r"^--\s?$")
SUBJECT_PREFIX_RE = re.compile(r"^\s*(Re|RE|Fwd|FW|Fw)\s*:\s*", re.IGNORECASE)
SUBJECT_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s*")

BOT_SUBJECT_RE = re.compile(
    r"^(I-D Action:|New Version Notification|WG Action:|Document Action:|Protocol Action:)",
    re.IGNORECASE,
)
BOT_FROM_RE = re.compile(
    r"(internet-drafts@ietf\.org|iesg-secretary@ietf\.org|rfc-editor@rfc-editor\.org)",
    re.IGNORECASE,
)


def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
    except Exception:
        return value
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def normalize_subject(subject: str) -> str:
    s = subject or ""
    for _ in range(4):
        prev = s
        s = SUBJECT_PREFIX_RE.sub("", s)
        s = SUBJECT_TAG_RE.sub("", s)
        s = s.strip()
        if s == prev:
            break
    return s


def clean_body(text: str) -> str:
    lines = text.split("\n")
    out = []
    for line in lines:
        if FOOTER_SEP_RE.match(line):
            break
        if SIG_DELIM_RE.match(line):
            break
        if QUOTE_LINE_RE.match(line):
            continue
        if ATTRIBUTION_RE.match(line.strip()):
            continue
        out.append(line)
    result = "\n".join(out)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        plain = None
        html = None
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and plain is None:
                plain = text
            elif ctype == "text/html" and html is None:
                html = text
        if plain is not None:
            return plain
        if html is not None:
            return re.sub(r"<[^>]+>", " ", html)
        return ""
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload is None:
                return str(msg.get_payload())
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        except Exception:
            return ""


def is_bot_message(subject: str, from_header: str) -> bool:
    return bool(BOT_SUBJECT_RE.match(subject or "")) or bool(BOT_FROM_RE.search(from_header or ""))


def message_to_record(msg: email.message.Message, list_name: str, fallback_id: str):
    subject = decode_mime_header(str(msg.get("Subject", "") or ""))
    from_header = str(msg.get("From", "") or "")

    if is_bot_message(subject, from_header):
        return None, "bot"

    display_name, addr = email.utils.parseaddr(from_header)
    display_name = decode_mime_header(display_name)
    author = display_name.strip() or (addr.split("@")[0] if addr else "unknown")

    date_hdr = msg.get("Date")
    date_str = None
    if date_hdr:
        try:
            dt = email.utils.parsedate_to_datetime(str(date_hdr))
            date_str = dt.date().isoformat()
        except Exception:
            date_str = None

    body = clean_body(extract_body(msg))
    if len(body) < MIN_BODY_CHARS:
        return None, "too_short"

    message_id = str(msg.get("Message-ID") or fallback_id).strip()
    in_reply_to = msg.get("In-Reply-To")
    in_reply_to = str(in_reply_to).strip() if in_reply_to else None

    record = {
        "id": f"{list_name}:{message_id}",
        "list": list_name,
        "date": date_str,
        "author": author,
        "subject": subject.strip(),
        "normalized_subject": normalize_subject(subject),
        "in_reply_to": in_reply_to,
        "body": body,
    }
    return record, "kept"


def process_eml_dir(list_name, path):
    kept, dropped_bot, dropped_short = 0, 0, 0
    records = []
    for fname in sorted(os.listdir(path)):
        fpath = os.path.join(path, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, "rb") as f:
            raw = f.read()
        try:
            msg = email.message_from_bytes(raw)
        except Exception:
            continue
        record, status = message_to_record(msg, list_name, fname)
        if status == "bot":
            dropped_bot += 1
        elif status == "too_short":
            dropped_short += 1
        else:
            kept += 1
            records.append(record)
    return records, kept, dropped_bot, dropped_short


def process_mbox_gz_dir(list_name, path):
    kept, dropped_bot, dropped_short = 0, 0, 0
    records = []
    for fname in sorted(os.listdir(path)):
        if not (fname.endswith(".mbox.gz") or fname.endswith(".txt.gz")):
            continue
        fpath = os.path.join(path, fname)
        with gzip.open(fpath, "rb") as gz, tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
            tmp.write(gz.read())
            tmp_path = tmp.name
        try:
            mbox = mailbox.mbox(tmp_path)
            for i, msg in enumerate(mbox):
                record, status = message_to_record(msg, list_name, f"{fname}#{i}")
                if status == "bot":
                    dropped_bot += 1
                elif status == "too_short":
                    dropped_short += 1
                else:
                    kept += 1
                    records.append(record)
        finally:
            os.unlink(tmp_path)
    return records, kept, dropped_bot, dropped_short


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    totals = {"kept": 0, "bot": 0, "short": 0}
    for list_name, path, kind in LIST_SOURCES:
        if not os.path.isdir(path):
            print(f"[{list_name}] SKIP (no directory: {path})")
            continue
        if kind == "eml":
            records, kept, dropped_bot, dropped_short = process_eml_dir(list_name, path)
        else:
            records, kept, dropped_bot, dropped_short = process_mbox_gz_dir(list_name, path)

        out_path = os.path.join(OUT_DIR, f"{list_name}.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        total_seen = kept + dropped_bot + dropped_short
        print(f"[{list_name}] {total_seen} seen -> {kept} kept, "
              f"{dropped_bot} dropped (bot), {dropped_short} dropped (too short) -> {out_path}")
        totals["kept"] += kept
        totals["bot"] += dropped_bot
        totals["short"] += dropped_short

    print(f"\nTotal: {totals['kept']} kept, {totals['bot']} bot-dropped, {totals['short']} short-dropped")


if __name__ == "__main__":
    main()
