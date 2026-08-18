"""Interactive DNS Expert chat CLI: retrieves relevant RFC/vendor-doc chunks
for each turn and streams a grounded answer from a local Ollama model.
"""
import argparse
import sys

import ollama

from dns_expert.retrieval import search, format_context, detect_product_filter

DEFAULT_MODEL = "dns-expert"
TOP_K = 8


def build_messages(history, query, context, include_discussions):
    if context:
        sources = "RFCs/vendor docs/IETF & DNS-OARC/RIPE mailing list archives" if include_discussions else "RFCs/vendor docs"
        user_turn = (
            f"Context (retrieved from {sources}, may be partial or irrelevant):\n\n"
            f"{context}\n\n---\n\nQuestion: {query}"
        )
    else:
        user_turn = query
    return history + [{"role": "user", "content": user_turn}]


def chat_once(client, model, history, query, top_k, verbose, include_discussions):
    product = detect_product_filter(query)
    results = search(query, top_k=top_k, product=product, include_discussions=include_discussions)
    context = format_context(results)

    if verbose:
        print(f"\n[retrieved {len(results)} chunks"
              f"{f', filtered to product=' + product if product else ''}]", file=sys.stderr)
        for r in results:
            if r["source_type"] == "discussion":
                src = f"{r['list']} ({r['date']})"
                heading = r["normalized_subject"]
            elif r["source_type"] == "rfc":
                src = f"RFC {r['rfc']}"
                heading = r["section"] or r["title"]
            else:
                src = r["product"]
                heading = r["section"] or r["title"]
            print(f"  - {src}: {heading} (dist={r['_distance']:.3f})", file=sys.stderr)

    messages = build_messages(history, query, context, include_discussions)

    print("\nDNS Expert: ", end="", flush=True)
    full_response = []
    for chunk in client.chat(model=model, messages=messages, stream=True):
        piece = chunk["message"]["content"]
        print(piece, end="", flush=True)
        full_response.append(piece)
    print()

    # Store the plain (un-augmented) turns in history so it doesn't balloon with context every turn
    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": "".join(full_response)})
    return history


def main():
    parser = argparse.ArgumentParser(description="Chat with the local DNS Expert model.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name (default: dns-expert)")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="Number of chunks to retrieve per turn")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print retrieved chunk sources")
    parser.add_argument("--discussions", action="store_true",
                         help="Also retrieve from IETF/DNS-OARC/RIPE mailing list archives (off by default)")
    parser.add_argument("question", nargs="*", help="Ask a single question and exit (non-interactive)")
    args = parser.parse_args()

    client = ollama.Client()
    history = []

    if args.question:
        query = " ".join(args.question)
        chat_once(client, args.model, history, query, args.top_k, args.verbose, args.discussions)
        return

    tagline = "RFCs, vendor docs, and mailing list archives" if args.discussions else "RFCs + vendor docs"
    print(f"DNS Expert — offline RAG chat over {tagline}. Ctrl-D or 'exit' to quit.\n")
    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in ("exit", "quit"):
            break
        history = chat_once(client, args.model, history, query, args.top_k, args.verbose, args.discussions)


if __name__ == "__main__":
    main()
