"""Unit tests for KnowledgeDB and HybridSearchEngine."""

import tempfile
import unittest
from pathlib import Path

from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.knowledge.search import HybridSearchEngine


class TestSearchEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_dns.db"
        self.db = KnowledgeDB(self.db_path)

        # Insert sample test chunks
        self.db.insert_chunk(
            source_type="rfc",
            source_id="rfc8484",
            title="RFC 8484: DNS Queries over HTTPS (DoH)",
            section="Section 4.1: The HTTP Method",
            content="A DoH client sends a DNS query using HTTP POST or GET request with application/dns-message content type.",
            embedding=[0.1] * 768,
        )
        self.db.insert_chunk(
            source_type="vendor_doc",
            source_id="unbound/conf.rst",
            title="UNBOUND - Configuration Guide",
            section="Section: QNAME Minimisation",
            vendor="unbound",
            content="qname-minimisation: yes enables QNAME minimisation as defined in RFC 7816 / RFC 9156.",
            embedding=[0.2] * 768,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_database_stats(self):
        stats = self.db.get_stats()
        self.assertEqual(stats["total_chunks"], 2)
        self.assertEqual(stats["chunks_with_embeddings"], 2)

    def test_fts5_lexical_search(self):
        results = self.db.fts_search("DoH HTTPS")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["source_id"], "rfc8484")

    def test_hybrid_search(self):
        engine = HybridSearchEngine(db=self.db)
        results = engine.search("qname minimisation in Unbound", top_k=2)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["vendor"], "unbound")
        self.assertIn("qname-minimisation", results[0]["content"])


if __name__ == "__main__":
    unittest.main()
