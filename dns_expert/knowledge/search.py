"""Hybrid Retrieval Engine combining Dense Vector Similarity and Lexical BM25 with RRF."""

import re
from typing import Any, Dict, List, Optional
import numpy as np

from dns_expert.config import DEFAULT_TOP_K, RRF_K_CONSTANT
from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.ollama_client import OllamaClient


class HybridSearchEngine:
    def __init__(self, db: Optional[KnowledgeDB] = None, ollama_client: Optional[OllamaClient] = None):
        self.db = db or KnowledgeDB()
        self.client = ollama_client or OllamaClient()
        self._cached_doc_ids: Optional[List[int]] = None
        self._cached_matrix: Optional[np.ndarray] = None
        self._cache_dirty = True

    def refresh_cache(self) -> None:
        doc_ids, matrix = self.db.load_vector_matrix()
        self._cached_doc_ids = doc_ids
        self._cached_matrix = matrix
        self._cache_dirty = False

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        source_type: Optional[str] = None,
        vendor: Optional[str] = None,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ) -> List[Dict[str, Any]]:
        if self._cache_dirty or self._cached_matrix is None:
            self.refresh_cache()

        fts_query = self._expand_dns_query(query)
        fts_results = self.db.fts_search(fts_query, limit=50, source_type=source_type, vendor=vendor)

        bm25_ranks: Dict[int, int] = {}
        for rank_idx, item in enumerate(fts_results, start=1):
            bm25_ranks[item["id"]] = rank_idx

        dense_ranks: Dict[int, int] = {}
        dense_sims: Dict[int, float] = {}

        if self._cached_matrix is not None and len(self._cached_doc_ids) > 0:
            try:
                q_emb = self.client.get_embedding(query)
                q_vec = np.array(q_emb, dtype=np.float32)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                    sims = np.dot(self._cached_matrix, q_vec)
                    top_indices = np.argsort(sims)[::-1][:50]
                    rank_counter = 1
                    for idx in top_indices:
                        doc_id = self._cached_doc_ids[idx]
                        score = float(sims[idx])
                        dense_ranks[doc_id] = rank_counter
                        dense_sims[doc_id] = score
                        rank_counter += 1
            except Exception:
                pass

        all_candidate_ids = set(bm25_ranks.keys()).union(dense_ranks.keys())
        if not all_candidate_ids:
            return []

        rrf_scores: Dict[int, float] = {}
        for doc_id in all_candidate_ids:
            score = 0.0
            if doc_id in dense_ranks:
                score += dense_weight * (1.0 / (RRF_K_CONSTANT + dense_ranks[doc_id]))
            if doc_id in bm25_ranks:
                score += bm25_weight * (1.0 / (RRF_K_CONSTANT + bm25_ranks[doc_id]))
            rrf_scores[doc_id] = score

        sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda d_id: rrf_scores[d_id], reverse=True)[:top_k]
        doc_map = self.db.get_documents_by_ids(sorted_doc_ids)

        results = []
        for d_id in sorted_doc_ids:
            doc = doc_map.get(d_id)
            if not doc:
                continue
            doc_copy = dict(doc)
            doc_copy["rrf_score"] = round(rrf_scores[d_id], 5)
            doc_copy["dense_sim"] = round(dense_sims.get(d_id, 0.0), 4)
            doc_copy["citation_label"] = self._format_citation_label(doc_copy)
            results.append(doc_copy)

        return results

    def _expand_dns_query(self, query: str) -> str:
        expanded = query
        rfc_matches = re.findall(r"rfc\s*(\d+)", query, re.IGNORECASE)
        for num in rfc_matches:
            expanded += f" rfc{num} rfc {num}"
        return expanded

    def _format_citation_label(self, doc: Dict[str, Any]) -> str:
        src_type = doc.get("source_type")
        title = doc.get("title", "")
        section = doc.get("section", "")
        vendor = doc.get("vendor", "")
        date = doc.get("date", "")

        if src_type == "rfc":
            return f"[{title} | {section}]"
        elif src_type == "vendor_doc":
            return f"[{vendor.upper()} Documentation | {section}]"
        elif src_type == "discussion":
            return f"[{title} | Date: {date}]"
        return f"[{title}]"
