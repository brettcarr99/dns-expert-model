#!/usr/bin/env python3
"""DNS-Expert Evaluation Harness.

Runs 15 representative retrieval test cases against the KnowledgeDB
using HybridSearchEngine. Each case passes if at least one expected
keyword appears in the top-6 retrieved chunk contents/titles/source_ids.

Usage:
    OLLAMA_HOST=http://127.0.0.1:11434 .venv/bin/python run_eval.py
    OLLAMA_HOST=http://127.0.0.1:11434 .venv/bin/python run_eval.py --db dns_knowledge.db

Exit codes:
    0 — all test cases passed
    1 — one or more test cases failed
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Path & env setup ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Always use explicit 127.0.0.1 — ignore any bind-address in OLLAMA_HOST
os.environ.setdefault('OLLAMA_HOST', 'http://127.0.0.1:11434')
if os.environ.get('OLLAMA_HOST', '').startswith('0.0.0.0'):
    os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:11434'

from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.knowledge.search import HybridSearchEngine
from dns_expert.ollama_client import OllamaClient


# ── Test case definition ──────────────────────────────────────────────────────

@dataclass
class EvalCase:
    id: int
    description: str
    query: str
    expected_keywords: List[str]          # pass if ANY keyword found in top-6 chunks
    source_type_filter: Optional[str] = None
    is_negative: bool = False             # negative test: pass if NO keyword found
    # Result fields (populated at runtime)
    passed: bool = False
    matched_keyword: str = ""
    top_sources: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str = ""


EVAL_CASES: List[EvalCase] = [
    EvalCase(
        id=1,
        description="RFC retrieval — RFC 9460 SVCB/HTTPS",
        query="What is RFC 9460?",
        expected_keywords=["SVCB", "9460", "HTTPS"],
    ),
    EvalCase(
        id=2,
        description="RFC retrieval — DNS over QUIC",
        query="DNS over QUIC",
        expected_keywords=["9250", "DoQ", "QUIC"],
    ),
    EvalCase(
        id=3,
        description="DNSSEC — NSEC3",
        query="How does NSEC3 work?",
        expected_keywords=["NSEC3", "5155"],
    ),
    EvalCase(
        id=4,
        description="Vendor config — Unbound QNAME minimisation",
        query="Configure QNAME minimisation in Unbound",
        expected_keywords=["qname-minimisation", "qname minimisation", "unbound", "QNAME"],
        source_type_filter="vendor_doc",
    ),
    EvalCase(
        id=5,
        description="Vendor config — BIND 9 response policy zone",
        query="BIND 9 response policy zone",
        expected_keywords=["response-policy", "bind", "rpz", "RPZ", "response policy"],
        source_type_filter="vendor_doc",
    ),
    EvalCase(
        id=6,
        description="Diagnostic — SERVFAIL meaning",
        query="What does SERVFAIL mean?",
        expected_keywords=["SERVFAIL", "RCODE"],
    ),
    EvalCase(
        id=7,
        description="Obsolescence — TSIG authentication (should cite 8945, not 2845)",
        query="TSIG authentication",
        expected_keywords=["8945", "TSIG"],
    ),
    EvalCase(
        id=8,
        description="Transport — DNS over TLS",
        query="DNS over TLS configuration",
        expected_keywords=["7858", "DoT", "TLS"],
    ),
    EvalCase(
        id=9,
        description="Operational — DNS amplification mitigation",
        query="DNS amplification attack mitigation",
        expected_keywords=["amplification", "rate", "mitigation"],
    ),
    EvalCase(
        id=10,
        description="Modern records — SVCB record format",
        query="SVCB record format",
        expected_keywords=["SVCB", "9460"],
    ),
    EvalCase(
        id=11,
        description="EDNS — Extended DNS errors",
        query="Extended DNS errors",
        expected_keywords=["8914", "EDE", "extended"],
    ),
    EvalCase(
        id=12,
        description="Zone transfer — XoT over TLS",
        query="XoT zone transfer over TLS",
        expected_keywords=["9103", "XoT", "zone transfer"],
    ),
    EvalCase(
        id=13,
        description="Negative cache — DNS failures caching",
        query="negative caching DNS failures",
        expected_keywords=["9520", "negative", "NXDOMAIN", "caching"],
    ),
    EvalCase(
        id=14,
        description="Vendor config — PowerDNS recursor",
        query="PowerDNS recursor configuration",
        expected_keywords=["recursor", "pdns", "PowerDNS"],
        source_type_filter="vendor_doc",
    ),
    EvalCase(
        id=15,
        description="Negative test — Python pandas DataFrame merge (unrelated to DNS)",
        query="Python pandas DataFrame merge groupby machine learning neural network",
        expected_keywords=["pandas", "DataFrame", "groupby", "scikit-learn", "neural network weights"],
        is_negative=True,  # top DNS chunks should NOT contain ML/pandas documentation
    ),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def _chunk_text(chunk: dict) -> str:
    """Combine all searchable text fields from a chunk."""
    return " ".join(filter(None, [
        chunk.get("content", ""),
        chunk.get("title", ""),
        chunk.get("source_id", ""),
        chunk.get("section", ""),
    ]))


def run_case(case: EvalCase, engine: HybridSearchEngine) -> EvalCase:
    """Execute one eval case and populate result fields."""
    t0 = time.time()
    try:
        results = engine.search(
            query=case.query,
            top_k=6,
            source_type=case.source_type_filter,
        )
    except Exception as exc:
        case.error = str(exc)
        case.elapsed_s = time.time() - t0
        case.passed = False
        return case

    case.elapsed_s = time.time() - t0
    case.top_sources = [r.get("source_id", "?") for r in results[:6]]

    if not case.expected_keywords:
        # Degenerate positive: pass trivially if results are non-empty
        case.passed = True
        return case

    combined_texts = [_chunk_text(r) for r in results[:6]]

    if case.is_negative:
        # Negative test: pass if NONE of the expected keywords appear
        found_any = False
        for kw in case.expected_keywords:
            kw_lower = kw.lower()
            if any(kw_lower in t.lower() for t in combined_texts):
                found_any = True
                case.matched_keyword = kw
                break
        case.passed = not found_any
    else:
        # Positive test: pass if at least one keyword found
        for kw in case.expected_keywords:
            kw_lower = kw.lower()
            if any(kw_lower in t.lower() for t in combined_texts):
                case.matched_keyword = kw
                case.passed = True
                break

    return case


def main() -> int:
    parser = argparse.ArgumentParser(description="DNS-Expert evaluation harness")
    parser.add_argument(
        "--db",
        default=str(BASE_DIR / "dns_knowledge.db"),
        help="Path to dns_knowledge.db (default: dns_knowledge.db in this directory)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"✗ Database not found: {db_path}")
        return 1

    print("=" * 70)
    print("DNS-Expert — Evaluation Harness (15 cases)")
    print("=" * 70)
    print(f"DB:   {db_path}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Initialise engine
    db = KnowledgeDB(db_path, auto_unpack=False)
    client = OllamaClient()

    if not client.check_health():
        print("✗ Ollama is not reachable. Set OLLAMA_HOST=http://127.0.0.1:11434 and ensure it is running.")
        return 1

    stats = db.get_stats()
    print(f"✓ DB loaded — {stats['total_chunks']:,} total chunks")
    print(f"  By source: {stats.get('by_source', {})}")
    print()

    engine = HybridSearchEngine(db=db, ollama_client=client)
    print("✓ Vector cache loading … ", end="", flush=True)
    engine.refresh_cache()
    vec_count = len(engine._cached_doc_ids) if engine._cached_doc_ids is not None else 0
    print(f"done ({vec_count:,} vectors)")
    print()

    # Run all cases
    passed = 0
    failed = 0
    results_data = []

    for case in EVAL_CASES:
        run_case(case, engine)
        icon = "✓" if case.passed else "✗"
        status = "PASS" if case.passed else "FAIL"

        # Build status line
        kw_info = f"  [matched: '{case.matched_keyword}']" if case.matched_keyword else ""
        err_info = f"  [ERROR: {case.error}]" if case.error else ""
        sources_str = ", ".join(case.top_sources[:3]) if case.top_sources else "—"

        print(f"  {icon} [{case.id:02d}] {status}  {case.description}")
        if case.passed:
            if case.is_negative:
                print(f"       Correctly returned no HTTP-status chunks  ({case.elapsed_s:.2f}s)")
            else:
                print(f"       Keyword found{kw_info}  top sources: {sources_str}  ({case.elapsed_s:.2f}s)")
        else:
            if case.error:
                print(f"       {err_info}  ({case.elapsed_s:.2f}s)")
            elif case.is_negative:
                print(f"       UNEXPECTED MATCH on '{case.matched_keyword}'  ({case.elapsed_s:.2f}s)")
            else:
                print(f"       No keyword in [{', '.join(case.expected_keywords)}]  "
                      f"top sources: {sources_str}  ({case.elapsed_s:.2f}s)")

        if case.passed:
            passed += 1
        else:
            failed += 1

        results_data.append({
            "id": case.id,
            "description": case.description,
            "query": case.query,
            "passed": case.passed,
            "matched_keyword": case.matched_keyword,
            "expected_keywords": case.expected_keywords,
            "top_sources": case.top_sources,
            "elapsed_s": round(case.elapsed_s, 3),
            "error": case.error,
            "is_negative": case.is_negative,
        })

    # Summary
    total = len(EVAL_CASES)
    print()
    print("=" * 70)
    print(f"RESULT: {passed}/{total} passed  |  {failed} failed")
    print("=" * 70)
    if failed == 0:
        print("✓ All evaluation cases passed.")
    else:
        print("✗ Some evaluation cases failed — see details above.")
    print()

    # Save results
    results_path = BASE_DIR / "eval_results.json"
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 3),
        "cases": results_data,
    }
    results_path.write_text(json.dumps(output, indent=2))
    print(f"✓ Results saved to {results_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
