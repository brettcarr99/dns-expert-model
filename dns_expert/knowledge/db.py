"""SQLite-based Hybrid Vector & Full-Text (FTS5) Storage Engine."""

import array
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from dns_expert.config import DB_PATH, ENCRYPTED_BLOB_PATH, USER_BLOB_PATH
from dns_expert.knowledge.crypto import decrypt_file


class KnowledgeDB:
    """High-performance SQLite database storing chunks, FTS5 index, and dense vectors."""

    def __init__(self, db_path: Optional[Path] = None, auto_unpack: bool = True):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if auto_unpack and (db_path is None or self.db_path.name == "dns_knowledge.db"):
            self._ensure_db_available()
        self._init_db()

    def _ensure_db_available(self) -> None:
        """Auto-decrypt encrypted knowledge blob if database is not present."""
        if self.db_path.exists() and self.db_path.stat().st_size > 0:
            return

        target_blob = None
        if ENCRYPTED_BLOB_PATH.exists():
            target_blob = ENCRYPTED_BLOB_PATH
        elif USER_BLOB_PATH.exists():
            target_blob = USER_BLOB_PATH

        if target_blob:
            try:
                decrypt_file(target_blob, self.db_path)
            except Exception:
                pass

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection with WAL mode and row factory."""
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA cache_size=-64000;")  # 64MB cache
        return con

    def _init_db(self) -> None:
        """Initialize schema: documents table, FTS5 virtual table, sync_state table."""
        with self._get_connection() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,       -- 'rfc', 'vendor_doc', 'discussion'
                    source_id TEXT NOT NULL,         -- 'rfc8484', 'bind9/zones.rst', etc.
                    title TEXT NOT NULL,
                    section TEXT,
                    vendor TEXT,
                    date TEXT,
                    url_or_path TEXT,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    content_hash TEXT               -- sha256(content) for idempotent upsert
                );
            """)

            # Safely add content_hash column to existing databases (migration)
            try:
                con.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT;")
            except sqlite3.OperationalError:
                pass  # column already exists

            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_docs_source ON documents (source_type, vendor);
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_docs_source_id ON documents (source_id);
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_docs_content_hash ON documents (content_hash);
            """)

            fts_exists = con.execute("""
                SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts';
            """).fetchone()

            if not fts_exists:
                con.execute("""
                    CREATE VIRTUAL TABLE documents_fts USING fts5(
                        content,
                        title,
                        section,
                        vendor,
                        source_type,
                        source_id,
                        content='documents',
                        content_rowid='id',
                        tokenize='unicode61 remove_diacritics 2'
                    );
                """)

                con.execute("""
                    CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
                        INSERT INTO documents_fts(rowid, content, title, section, vendor, source_type, source_id)
                        VALUES (new.id, new.content, new.title, new.section, new.vendor, new.source_type, new.source_id);
                    END;
                """)
                con.execute("""
                    CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
                        INSERT INTO documents_fts(documents_fts, rowid, content, title, section, vendor, source_type, source_id)
                        VALUES('delete', old.id, old.content, old.title, old.section, old.vendor, old.source_type, old.source_id);
                    END;
                """)
                con.execute("""
                    CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
                        INSERT INTO documents_fts(documents_fts, rowid, content, title, section, vendor, source_type, source_id)
                        VALUES('delete', old.id, old.content, old.title, old.section, old.vendor, old.source_type, old.source_id);
                        INSERT INTO documents_fts(rowid, content, title, section, vendor, source_type, source_id)
                        VALUES (new.id, new.content, new.title, new.section, new.vendor, new.source_type, new.source_id);
                    END;
                """)

            # sync_state table: tracks last sync watermark and embed model per source type
            con.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    source_type TEXT PRIMARY KEY,  -- 'rfc', 'vendor_doc', 'discussion', 'draft'
                    last_sync_ts TEXT,             -- ISO8601 timestamp
                    upstream_watermark TEXT,       -- RFC index version, git SHA, last message hash, etc.
                    embed_model TEXT,              -- must match current EMBED_MODEL
                    embed_dim INTEGER              -- must match EMBEDDING_DIM
                );
            """)

            con.commit()

    # ── Insertion ─────────────────────────────────────────────────────────────

    def insert_chunk(
        self,
        source_type: str,
        source_id: str,
        title: str,
        content: str,
        section: Optional[str] = None,
        vendor: Optional[str] = None,
        date: Optional[str] = None,
        url_or_path: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> int:
        """Insert a single document chunk with optional embedding blob."""
        emb_blob = None
        if embedding is not None:
            emb_blob = array.array('f', embedding).tobytes()

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        with self._get_connection() as con:
            cur = con.execute(
                """
                INSERT INTO documents (source_type, source_id, title, section, vendor, date, url_or_path, content, embedding, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (source_type, source_id, title, section, vendor, date, url_or_path, content, emb_blob, content_hash),
            )
            con.commit()
            return cur.lastrowid

    def insert_chunks_batch(self, chunks: List[Dict[str, Any]]) -> int:
        """Batch insert chunks for high throughput."""
        rows = []
        for ch in chunks:
            emb_blob = None
            emb = ch.get("embedding")
            if emb is not None:
                emb_blob = array.array('f', emb).tobytes()

            content = ch.get("content", "")
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            rows.append((
                ch.get("source_type", ""),
                ch.get("source_id", ""),
                ch.get("title", ""),
                ch.get("section"),
                ch.get("vendor"),
                ch.get("date"),
                ch.get("url_or_path"),
                content,
                emb_blob,
                content_hash,
            ))

        with self._get_connection() as con:
            con.executemany(
                """
                INSERT INTO documents (source_type, source_id, title, section, vendor, date, url_or_path, content, embedding, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                rows,
            )
            con.commit()
        return len(rows)

    # ── Upsert / Idempotent sync ───────────────────────────────────────────────

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        """Return sha256 hex digest of content string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def upsert_chunk(self, chunk_dict: Dict[str, Any]) -> str:
        """Idempotent upsert for a single chunk.

        Returns:
            'inserted'  — chunk is new; was inserted
            'updated'   — source_id existed with different content; old deleted, new inserted
            'skipped'   — source_id + content_hash identical; no-op
        """
        source_id = chunk_dict["source_id"]
        content = chunk_dict.get("content", "")
        new_hash = self._compute_content_hash(content)

        emb_blob = None
        emb = chunk_dict.get("embedding")
        if emb is not None:
            emb_blob = array.array('f', emb).tobytes()

        with self._get_connection() as con:
            existing = con.execute(
                "SELECT id, content_hash FROM documents WHERE source_id = ? LIMIT 1;",
                (source_id,),
            ).fetchone()

            if existing is not None:
                if existing["content_hash"] == new_hash:
                    return "skipped"
                # Content changed — delete all old chunks for this source_id and re-insert
                con.execute("DELETE FROM documents WHERE source_id = ?;", (source_id,))

            con.execute(
                """
                INSERT INTO documents (source_type, source_id, title, section, vendor, date, url_or_path, content, embedding, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    chunk_dict.get("source_type", ""),
                    source_id,
                    chunk_dict.get("title", ""),
                    chunk_dict.get("section"),
                    chunk_dict.get("vendor"),
                    chunk_dict.get("date"),
                    chunk_dict.get("url_or_path"),
                    content,
                    emb_blob,
                    new_hash,
                ),
            )
            con.commit()

        return "updated" if existing is not None else "inserted"

    # ── Obsolescence ──────────────────────────────────────────────────────────

    def mark_obsolete(self, source_id: str, superseded_by: str) -> int:
        """Prefix all chunk titles for source_id with '[OBSOLETED by RFCxxxx] '.

        Returns:
            Number of chunks updated.
        """
        prefix = f"[OBSOLETED by {superseded_by.upper()}] "
        with self._get_connection() as con:
            # Only prefix if not already prefixed
            cur = con.execute(
                """
                UPDATE documents
                SET title = ? || title
                WHERE source_id = ? AND title NOT LIKE '[OBSOLETED%';
                """,
                (prefix, source_id),
            )
            con.commit()
            return cur.rowcount

    # ── Source ID queries ─────────────────────────────────────────────────────

    def get_existing_source_ids(self, source_type: Optional[str] = None) -> Set[str]:
        """Return a set of all source_ids currently in the DB.

        Args:
            source_type: If provided, filter to only this source type
                         (e.g. 'rfc', 'vendor_doc', 'discussion').
        """
        if source_type:
            sql = "SELECT DISTINCT source_id FROM documents WHERE source_type = ?;"
            params = [source_type]
        else:
            sql = "SELECT DISTINCT source_id FROM documents;"
            params = []

        with self._get_connection() as con:
            rows = con.execute(sql, params).fetchall()
        return {r["source_id"] for r in rows}

    # ── Sync state ────────────────────────────────────────────────────────────

    def update_sync_state(
        self,
        source_type: str,
        watermark: str,
        embed_model: str,
        embed_dim: int,
    ) -> None:
        """Upsert sync metadata for a given source type."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO sync_state (source_type, last_sync_ts, upstream_watermark, embed_model, embed_dim)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_type) DO UPDATE SET
                    last_sync_ts = excluded.last_sync_ts,
                    upstream_watermark = excluded.upstream_watermark,
                    embed_model = excluded.embed_model,
                    embed_dim = excluded.embed_dim;
                """,
                (source_type, ts, watermark, embed_model, embed_dim),
            )
            con.commit()

    def get_sync_state(self, source_type: str) -> Optional[Dict[str, Any]]:
        """Retrieve sync state for a source type, or None if never synced."""
        with self._get_connection() as con:
            row = con.execute(
                "SELECT * FROM sync_state WHERE source_type = ?;",
                (source_type,),
            ).fetchone()
        return dict(row) if row else None

    # ── Vector & FTS retrieval ─────────────────────────────────────────────────

    def load_vector_matrix(
        self, source_type: Optional[str] = None, vendor: Optional[str] = None
    ) -> Tuple[List[int], np.ndarray]:
        """Load all embeddings into an aligned NumPy float32 matrix for ultrafast cosine similarity."""
        query = "SELECT id, embedding FROM documents WHERE embedding IS NOT NULL"
        params = []
        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        if vendor:
            query += " AND vendor = ?"
            params.append(vendor)

        with self._get_connection() as con:
            cur = con.execute(query, params)
            rows = cur.fetchall()

            if not rows:
                return [], np.empty((0, 0), dtype=np.float32)

            doc_ids = []
            vectors = []
            for r in rows:
                blob = r["embedding"]
                if blob:
                    arr = np.frombuffer(blob, dtype=np.float32)
                    doc_ids.append(r["id"])
                    vectors.append(arr)

        if not vectors:
            return [], np.empty((0, 0), dtype=np.float32)

        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        return doc_ids, matrix

    def fts_search(
        self,
        query: str,
        limit: int = 50,
        source_type: Optional[str] = None,
        vendor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Perform lexical BM25 search against SQLite FTS5 table."""
        cleaned_words = []
        for w in query.replace('"', '').replace("'", "").replace(':', ' ').replace('-', ' ').split():
            w = w.strip()
            if len(w) > 1:
                cleaned_words.append(f'"{w}"')

        if not cleaned_words:
            return []

        fts_query = " OR ".join(cleaned_words)

        sql = """
            SELECT d.id, d.source_type, d.source_id, d.title, d.section, d.vendor,
                   d.date, d.url_or_path, d.content, bm25(documents_fts) as rank
            FROM documents_fts f
            JOIN documents d ON f.rowid = d.id
            WHERE documents_fts MATCH ?
        """
        params = [fts_query]

        if source_type:
            sql += " AND d.source_type = ?"
            params.append(source_type)
        if vendor:
            sql += " AND d.vendor = ?"
            params.append(vendor)

        sql += " ORDER BY rank LIMIT ?;"
        params.append(limit)

        with self._get_connection() as con:
            cur = con.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        return rows

    def get_documents_by_ids(self, doc_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Fetch full document details for a list of document IDs."""
        if not doc_ids:
            return {}

        placeholders = ",".join("?" * len(doc_ids))
        sql = f"""
            SELECT id, source_type, source_id, title, section, vendor, date, url_or_path, content
            FROM documents
            WHERE id IN ({placeholders});
        """
        with self._get_connection() as con:
            cur = con.execute(sql, doc_ids)
            return {r["id"]: dict(r) for r in cur.fetchall()}

    def get_stats(self) -> Dict[str, Any]:
        """Get database chunk counts and statistics."""
        with self._get_connection() as con:
            total = con.execute("SELECT COUNT(*) FROM documents;").fetchone()[0]
            with_emb = con.execute("SELECT COUNT(*) FROM documents WHERE embedding IS NOT NULL;").fetchone()[0]

            cur = con.execute("SELECT source_type, COUNT(*) as cnt FROM documents GROUP BY source_type;")
            by_source = {r["source_type"]: r["cnt"] for r in cur.fetchall()}

            cur = con.execute("SELECT vendor, COUNT(*) as cnt FROM documents WHERE vendor IS NOT NULL GROUP BY vendor;")
            by_vendor = {r["vendor"]: r["cnt"] for r in cur.fetchall()}

        size_mb = (self.db_path.stat().st_size / (1024 * 1024)) if self.db_path.exists() else 0.0

        return {
            "total_chunks": total,
            "chunks_with_embeddings": with_emb,
            "by_source": by_source,
            "by_vendor": by_vendor,
            "db_path": str(self.db_path),
            "size_mb": round(size_mb, 2),
        }
