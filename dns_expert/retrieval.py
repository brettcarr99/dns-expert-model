"""Query-time retrieval over the local LanceDB chunk index."""
import os

import lancedb
import ollama

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_DIR = os.path.join(BASE, "data", "index")
EMBED_MODEL = "nomic-embed-text"

_db = None
_table = None
_client = None


def _get_table():
    global _db, _table
    if _table is None:
        _db = lancedb.connect(INDEX_DIR)
        _table = _db.open_table("chunks")
    return _table


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


def search(query: str, top_k: int = 8, product: str | None = None):
    table = _get_table()
    client = _get_client()

    resp = client.embed(model=EMBED_MODEL, input=[f"search_query: {query}"])
    vector = resp["embeddings"][0]

    q = table.search(vector, vector_column_name="vector").metric("cosine")
    if product:
        q = q.where(f"product = '{product}'", prefilter=True)
    results = q.limit(top_k).to_list()
    return results


def format_context(results):
    if not results:
        return ""
    blocks = []
    for r in results:
        source = f"RFC {r['rfc']}" if r["source_type"] == "rfc" else f"{r['product']} docs"
        blocks.append(f"[{source} — {r['section'] or r['title']}]\n{r['text']}")
    return "\n\n---\n\n".join(blocks)
