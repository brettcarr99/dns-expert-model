"""SQLite-based Hybrid Vector & Full-Text (FTS5) Storage Engine."""

import array
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from dns_expert.config import DB_PATH


class KnowledgeDB:
    """High-performance SQLite database storing chunks, FTS5 index, and dense vectors."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection with WAL mode and row factory."""
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA cache_size=-64000;")  # 64MB cache
        return con

    def _init_db(self) -> None:
        """Initialize schema: documents table and FTS5 virtual table."""
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
                    embedding BLOB
                );
            """)

            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_docs_source ON documents (source_type, vendor);
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_docs_source_id ON documents (source_id);
            """)

            # Check if FTS table exists
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

                # Triggers to keep FTS table in sync with documents table
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
            con.commit()

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

        with self._get_connection() as con:
            cur = con.execute(
                """
                INSERT INTO documents (source_type, source_id, title, section, vendor, date, url_or_path, content, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (source_type, source_id, title, section, vendor, date, url_or_path, content, emb_blob),
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

            rows.append((
                ch.get("source_type", ""),
                ch.get("source_id", ""),
                ch.get("title", ""),
                ch.get("section"),
                ch.get("vendor"),
                ch.get("date"),
                ch.get("url_or_path"),
                ch.get("content", ""),
                emb_blob,
            ))

        with self._get_connection() as con:
            con.executemany(
                """
                INSERT INTO documents (source_type, source_id, title, section, vendor, date, url_or_path, content, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                rows,
            )
            con.commit()
        return len(rows)

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
        # Normalize matrix rows to unit length for direct dot-product cosine similarity
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
        # Clean query for FTS5 syntax
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
