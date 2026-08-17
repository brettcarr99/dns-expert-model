"""Phase 4 eval runner: executes data/eval/eval_set.json against the
dns-expert model, scores retrieval hits + keyword coverage in the answer,
and writes a markdown report.

Case types:
  "qa" / "config" — expects expected_keywords (each entry either a string,
      required verbatim, or a list of acceptable alternatives) and either
      expected_rfc or expected_product to check retrieval quality against.
  "negative" — deliberately unanswerable from the corpus (fabricated
      setting, source-level implementation detail, false premise, etc).
      Passes if the answer contains hedging/uncertainty language instead of
      a confidently fabricated specific fact.
"""
import json
import os
import time

import ollama

from dns_expert.retrieval import search, format_context, detect_product_filter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_SET_PATH = os.path.join(BASE, "data", "eval", "eval_set.json")
REPORT_PATH = os.path.join(BASE, "data", "eval", "report.md")
MODEL = "dns-expert"
TOP_K = 8

HEDGE_PHRASES = [
    "don't have", "do not have", "not covered", "not specified", "no information",
    "not documented", "not sure", "cannot confirm", "can't confirm",
    "does not appear", "doesn't appear", "not something i have", "unable to find",
    "not able to confirm", "outside the provided context", "not in the retrieved",
    "not in the provided", "isn't documented", "isn't specified", "no specific",
    "not explicitly", "doesn't specify", "does not specify", "not aware of",
    "doesn't have its own", "does not have its own", "doesn't implement",
    "does not implement", "no such", "not a real", "not an actual",
    "not a documented", "not a valid", "incorrect premise", "misconception",
    "does not contain", "doesn't contain", "cannot provide", "can't provide",
    "would need to refer", "you would need", "i cannot", "i can't",
    "not mention", "doesn't mention", "no mention",
]


def matches(keyword_entry, answer_lower, answer_lower_nocomma):
    alternatives = keyword_entry if isinstance(keyword_entry, list) else [keyword_entry]
    return any(alt.lower() in answer_lower or alt.lower() in answer_lower_nocomma for alt in alternatives)


def label(keyword_entry):
    return " | ".join(keyword_entry) if isinstance(keyword_entry, list) else keyword_entry


def run_case(client, case):
    query = case["query"]
    results = search(query, top_k=TOP_K, product=None)  # no filter: test unaided retrieval
    context = format_context(results)

    user_turn = f"Context (retrieved from RFCs/vendor docs, may be partial or irrelevant):\n\n{context}\n\n---\n\nQuestion: {query}"
    resp = client.chat(model=MODEL, messages=[{"role": "user", "content": user_turn}])
    answer = resp["message"]["content"]
    answer_lower = answer.lower()
    answer_lower_nocomma = answer_lower.replace(",", "")

    top_sources = [
        (f"RFC {r['rfc']}" if r["source_type"] == "rfc" else r["product"]) for r in results[:5]
    ]

    if case["type"] == "negative":
        hedged = any(p in answer_lower for p in HEDGE_PHRASES)
        return {
            "id": case["id"], "type": "negative", "query": query,
            "retrieval_hit": None, "keyword_hits": {}, "passed": hedged,
            "answer": answer, "top_sources": top_sources,
        }

    retrieval_hit = False
    if case.get("expected_rfc"):
        retrieval_hit = any(r["source_type"] == "rfc" and r["rfc"] == case["expected_rfc"] for r in results)
    elif case.get("expected_product"):
        retrieval_hit = any(r["source_type"] == "vendor" and r["product"] == case["expected_product"] for r in results)

    keyword_hits = {label(kw): matches(kw, answer_lower, answer_lower_nocomma) for kw in case["expected_keywords"]}
    all_keywords_found = all(keyword_hits.values())

    return {
        "id": case["id"], "type": case["type"], "query": query,
        "retrieval_hit": retrieval_hit, "keyword_hits": keyword_hits,
        "passed": retrieval_hit and all_keywords_found,
        "answer": answer, "top_sources": top_sources,
    }


def main():
    with open(EVAL_SET_PATH) as f:
        cases = json.load(f)

    client = ollama.Client()
    results = []
    start = time.time()
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}...")
        results.append(run_case(client, case))
    elapsed = time.time() - start

    n = len(results)
    non_neg = [r for r in results if r["type"] != "negative"]
    neg = [r for r in results if r["type"] == "negative"]
    retrieval_pass = sum(1 for r in non_neg if r["retrieval_hit"])
    keyword_pass = sum(1 for r in non_neg if all(r["keyword_hits"].values()))
    both_pass = sum(1 for r in non_neg if r["passed"])
    neg_pass = sum(1 for r in neg if r["passed"])

    lines = []
    lines.append("# DNS Expert eval report\n")
    lines.append(
        f"Cases: {n} ({len(non_neg)} qa/config + {len(neg)} negative) | "
        f"Retrieval hit: {retrieval_pass}/{len(non_neg)} | "
        f"Keyword coverage: {keyword_pass}/{len(non_neg)} | "
        f"Both: {both_pass}/{len(non_neg)} | "
        f"Negative-case hedge rate: {neg_pass}/{len(neg)} | "
        f"Wall time: {elapsed:.0f}s\n"
    )
    lines.append("## QA / config cases\n")
    lines.append("| id | type | retrieval | keywords | sources (top 5) |")
    lines.append("|---|---|---|---|---|")
    for r in non_neg:
        kw = ", ".join(f"{'OK' if v else 'MISS'}:{k}" for k, v in r["keyword_hits"].items())
        lines.append(f"| {r['id']} | {r['type']} | {'HIT' if r['retrieval_hit'] else 'MISS'} | {kw} | {', '.join(r['top_sources'])} |")

    lines.append("\n## Negative (should-decline) cases\n")
    lines.append("| id | hedged? | sources (top 5) |")
    lines.append("|---|---|---|")
    for r in neg:
        lines.append(f"| {r['id']} | {'YES' if r['passed'] else 'NO — check for fabrication'} | {', '.join(r['top_sources'])} |")

    lines.append("\n## Full answers\n")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(f"### [{status}] {r['id']} — {r['query']}\n")
        lines.append(r["answer"])
        lines.append("\n---\n")

    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))

    print(f"\nRetrieval hit: {retrieval_pass}/{len(non_neg)}  Keyword coverage: {keyword_pass}/{len(non_neg)}  "
          f"Both: {both_pass}/{len(non_neg)}  Negative hedge rate: {neg_pass}/{len(neg)}")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
