"""Query-time retrieval over the local LanceDB chunk index."""
import os

import lancedb
import ollama

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_DIR = os.path.join(BASE, "data", "index")
DISCUSSIONS_INDEX_DIR = os.path.join(BASE, "data", "index_discussions")
EMBED_MODEL = "nomic-embed-text"

# Validated in data/eval/discussions_report.md: 12/12 retrieval hit, 12/12
# effectively correct (one keyword-check false negative, not a real miss),
# 3/3 negative-case hedge rate -- see scripts/run_discussions_eval.py.
# The main RFC/vendor index is a wholly separate table/directory from the
# discussions index -- set this back to False, or pass
# include_discussions=False to search(), to fall back to RFC/vendor-only
# with zero effect on that index either way.
INCLUDE_DISCUSSIONS_DEFAULT = True

# RFCs/vendor docs are normative; mailing list posts are opinions/debate
# (see the Modelfile's source-trust framing). This small cosine-distance
# penalty on discussion results breaks near-ties in favor of the normative
# source without stopping discussions from winning a slot when they're
# genuinely more relevant by a real margin. Calibrated against a case found
# in eval: RFC 8484 (the actual DoH RFC) at distance 0.2198 lost its top-8
# slot to a discussion chunk at 0.2194 -- a 0.0003 margin, not a real
# relevance gap.
DISCUSSION_DISTANCE_PENALTY = 0.01

_db = None
_table = None
_discussions_db = None
_discussions_table = None
_client = None


def _get_table():
    global _db, _table
    if _table is None:
        _db = lancedb.connect(INDEX_DIR)
        _table = _db.open_table("chunks")
    return _table


def _get_discussions_table():
    global _discussions_db, _discussions_table
    if _discussions_table is None:
        if not os.path.isdir(DISCUSSIONS_INDEX_DIR):
            return None
        _discussions_db = lancedb.connect(DISCUSSIONS_INDEX_DIR)
        _discussions_table = _discussions_db.open_table("chunks")
    return _discussions_table


def _get_client():
    global _client
    if _client is None:
        _client = ollama.Client()
    return _client


PRODUCTS = {
    "bind9", "pdns-auth", "pdns-recursor", "dnsdist", "knot-dns",
    "knot-resolver", "unbound", "nsd", "coredns", "dnsmasq", "technitium",
}


def detect_product_filter(query: str):
    """Best-effort: if the query clearly names one vendor, bias retrieval to it."""
    q = query.lower()
    aliases = {
        "bind9": ["bind9", "bind 9", " bind ", "named.conf", "named-checkconf"],
        "pdns-auth": ["powerdns authoritative", "pdns-auth", "pdns auth"],
        "pdns-recursor": ["powerdns recursor", "pdns-recursor", "pdns recursor"],
        "dnsdist": ["dnsdist"],
        "knot-dns": ["knot dns", "knotd", "knot-dns"],
        "knot-resolver": ["knot resolver", "kresd"],
        "unbound": ["unbound"],
        "nsd": [" nsd ", "nsd.conf"],
        "coredns": ["coredns", "corefile"],
        "dnsmasq": ["dnsmasq"],
        "technitium": ["technitium"],
    }
    hits = [p for p, needles in aliases.items() if any(n in f" {q} " for n in needles)]
    return hits[0] if len(hits) == 1 else None


def search(query: str, top_k: int = 8, product: str | None = None, include_discussions: bool | None = None):
    if include_discussions is None:
        include_discussions = INCLUDE_DISCUSSIONS_DEFAULT

    table = _get_table()
    client = _get_client()

    resp = client.embed(model=EMBED_MODEL, input=[f"search_query: {query}"])
    vector = resp["embeddings"][0]

    q = table.search(vector, vector_column_name="vector").metric("cosine")
    if product:
        q = q.where(f"product = '{product}'", prefilter=True)
    results = q.limit(top_k).to_list()

    if include_discussions:
        d_table = _get_discussions_table()
        if d_table is not None:
            d_results = (
                d_table.search(vector, vector_column_name="vector")
                .metric("cosine")
                .limit(top_k)
                .to_list()
            )
            # Same embedding model/metric for both tables -> distances are
            # directly comparable, so a straight merge-and-resort gives
            # discussions a fair shot at ranking rather than a fixed quota --
            # tempered by DISCUSSION_DISTANCE_PENALTY so near-ties favor the
            # normative source (see its comment above).
            for r in d_results:
                r["_distance"] = r["_distance"] + DISCUSSION_DISTANCE_PENALTY
            results = sorted(results + d_results, key=lambda r: r["_distance"])[:top_k]

    return results


def format_context(results):
    if not results:
        return ""
    blocks = []
    for r in results:
        if r["source_type"] == "discussion":
            source = f"{r['list']} mailing list, {r['date']}, {r['author']}"
            heading = r["normalized_subject"]
        elif r["source_type"] == "rfc":
            source = f"RFC {r['rfc']}"
            heading = r["section"] or r["title"]
        else:
            source = f"{r['product']} docs"
            heading = r["section"] or r["title"]
        blocks.append(f"[{source} — {heading}]\n{r['text']}")
    return "\n\n---\n\n".join(blocks)
