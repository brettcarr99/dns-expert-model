"""Validation eval for the (currently opt-in, off-by-default) mailing-list
archive retrieval. Same methodology as scripts/run_eval.py: retrieval-hit +
keyword-coverage for qa cases, hedge-detection for negative cases -- run
with include_discussions=True regardless of the module default, since this
script's whole purpose is deciding whether that default should flip to on.
"""
import json
import os
import time

import ollama

from dns_expert.retrieval import search, format_context

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_SET_PATH = os.path.join(BASE, "data", "eval", "discussions_eval_set.json")
REPORT_PATH = os.path.join(BASE, "data", "eval", "discussions_report.md")
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


def matches(keyword_entry, answer_lower):
    alternatives = keyword_entry if isinstance(keyword_entry, list) else [keyword_entry]
    return any(alt.lower() in answer_lower for alt in alternatives)


def label(keyword_entry):
    return " | ".join(keyword_entry) if isinstance(keyword_entry, list) else keyword_entry


def run_case(client, case):
    query = case["query"]
    results = search(query, top_k=TOP_K, product=None, include_discussions=True)
    context = format_context(results)

    user_turn = (
        f"Context (retrieved from RFCs/vendor docs/IETF & DNS-OARC/RIPE mailing "
        f"list archives, may be partial or irrelevant):\n\n{context}\n\n---\n\n"
        f"Question: {query}"
    )
    resp = client.chat(model=MODEL, messages=[{"role": "user", "content": user_turn}])
    answer = resp["message"]["content"]
    answer_lower = answer.lower()

    top_sources = [
        (f"{r['list']} ({r['date']})" if r["source_type"] == "discussion"
         else (f"RFC {r['rfc']}" if r["source_type"] == "rfc" else r["product"]))
        for r in results[:5]
    ]

    if case["type"] == "negative":
        hedged = any(p in answer_lower for p in HEDGE_PHRASES)
        return {
            "id": case["id"], "type": "negative", "query": query,
            "retrieval_hit": None, "keyword_hits": {}, "passed": hedged,
            "answer": answer, "top_sources": top_sources,
        }

    retrieval_hit = any(
        r.get("source_type") == "discussion" and r.get("list") == case["expected_list"]
        for r in results
    )
    keyword_hits = {label(kw): matches(kw, answer_lower) for kw in case["expected_keywords"]}
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
    lines.append("# DNS Expert mailing-list-discussions eval report\n")
    lines.append(
        f"Cases: {n} ({len(non_neg)} qa + {len(neg)} negative) | "
        f"Retrieval hit: {retrieval_pass}/{len(non_neg)} | "
        f"Keyword coverage: {keyword_pass}/{len(non_neg)} | "
        f"Both: {both_pass}/{len(non_neg)} | "
        f"Negative-case hedge rate: {neg_pass}/{len(neg)} | "
        f"Wall time: {elapsed:.0f}s\n"
    )
    lines.append("## QA cases\n")
    lines.append("| id | retrieval | keywords | sources (top 5) |")
    lines.append("|---|---|---|---|")
    for r in non_neg:
        kw = ", ".join(f"{'OK' if v else 'MISS'}:{k}" for k, v in r["keyword_hits"].items())
        lines.append(f"| {r['id']} | {'HIT' if r['retrieval_hit'] else 'MISS'} | {kw} | {', '.join(r['top_sources'])} |")

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
