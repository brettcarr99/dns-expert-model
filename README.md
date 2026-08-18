# DNS Expert

An offline, RAG-grounded DNS expert that runs entirely on local Ollama models.
It answers protocol questions, troubleshoots, and generates server configs for
BIND9, PowerDNS (Authoritative + Recursor), dnsdist, Knot DNS, Knot Resolver,
Unbound, NSD, CoreDNS, dnsmasq, and Technitium — grounded in and citing the
actual RFCs and vendor documentation, not model memory. It can also draw on
~31.5k messages from a decade of IETF dnsop/dns-privacy/dd, DNS-OARC, and
RIPE DNS WG mailing list discussion (on by default; `--no-discussions` to
turn it off).

**Just want to install and use it?** See [`USER_GUIDE.md`](USER_GUIDE.md) for
plain-language, step-by-step instructions — no AI background assumed. The
rest of this file documents how the system is built, for anyone modifying
the pipeline itself.

## How it works

Rather than fine-tuning a model on the corpus (unreliable for exact syntax,
defaults, and RFC section recall at this corpus size), this retrieves relevant
passages at query time and feeds them to the chat model as context, with
citation instructions in the system prompt. See
`data/rfcs/`, `data/vendor_docs/` for source material and
`dns_expert/retrieval.py` for the retrieval logic.

Pipeline:
1. `scripts/clean_rfcs.py` — strip RFC-editor pagination boilerplate
2. `scripts/clean_vendor_docs.py` — normalize rst/md/html vendor docs to plain text
3. `scripts/build_chunks.py` — section-aware chunking with citation breadcrumbs (~11.8k chunks)
4. `scripts/enrich_chunks.py` — for short/terse chunks (config directive references etc,
   ~1.2k of them), generates a one-sentence natural-language paraphrase locally
   (`lfm2.5:8b`) and inserts it into the chunk text, so embeddings align better with
   how users actually phrase questions -> `data/chunks/chunks_enriched.jsonl`
5. `scripts/build_index.py` — embed via `nomic-embed-text`, store in local LanceDB (`data/index/`).
   Deliberately brute-force cosine search, no ANN index — see Known limitations.
6. `scripts/parse_discussions.py` — parses `.eml` files and gzipped mbox digests from
   `data/discussions/` (IETF dnsop/dns-privacy/dd, DNS-OARC, RIPE DNS WG), strips
   quoted-reply chains/signatures/list-footer boilerplate, drops auto-generated bot
   messages and near-empty replies -> `data/discussions_clean/*.jsonl`
7. `scripts/build_discussion_chunks.py` — chunks cleaned messages with citation
   breadcrumbs (list, date, author, subject) -> `data/chunks/discussions_chunks.jsonl`
8. `scripts/build_discussions_index.py` — embeds into a **separate** LanceDB table
   (`data/index_discussions/`) so it's fully independent of the RFC/vendor index;
   deleting this directory has zero effect on the rest of the system
9. `Modelfile` — DNS-expert system prompt layered over `qwen2.5:32b-instruct`, registered as Ollama model `dns-expert`
10. `dns_expert/cli.py` / `dns_expert/retrieval.py` — retrieves top-k chunks per turn
    (merging in mailing-list results by raw cosine distance when enabled — same
    embedding model for both indexes, so distances are directly comparable), streams
    a grounded answer

Everything runs locally through Ollama — no cloud calls, no API keys.

## Setup

Prerequisites: [Ollama](https://ollama.com) installed, Python 3.10+, ~25GB free
disk (base model + embedding model + corpus + index).

```bash
./scripts/setup.sh
```

This creates a venv, installs dependencies, pulls `nomic-embed-text` and
`qwen2.5:32b-instruct`, runs the full cleaning/chunking/embedding pipeline, and
registers the `dns-expert` Ollama model. Safe to re-run — every stage
overwrites its own output.

## Usage

```bash
./bin/dns-expert                              # interactive chat
./bin/dns-expert "how do I enable DNSSEC in unbound?"   # one-off question
./bin/dns-expert -v "..."                     # -v prints which chunks were retrieved
./bin/dns-expert --no-discussions "..."       # RFCs + vendor docs only, no mailing lists
```

## Evaluating changes

`data/eval/eval_set.json` holds test cases (protocol facts + vendor config
questions + config-generation tasks) with expected retrieved sources and
expected keywords in the answer.

```bash
python3 scripts/run_eval.py
```

Writes `data/eval/report.md` with per-case retrieval-hit / keyword-coverage
results and full transcripts. Current baseline (49 cases across all 11
vendors): retrieval hit **42/42**, keyword coverage 39/42, both 39/42 on
QA/config cases, and 7/7 on negative (should-decline) cases. The remaining
misses are documented below.

`data/eval/discussions_eval_set.json` / `scripts/run_discussions_eval.py` is
the equivalent for mailing-list retrieval (12 QA cases hand-written from real
threads across all 5 lists + 3 negative cases) -> `data/eval/discussions_report.md`.
Current baseline: retrieval hit 12/12, keyword coverage 11/12 (the one miss
is a hyphenation mismatch in the eval script's own keyword check, not a real
failure — the answer was correct), 3/3 negative hedge rate.

Re-run both after changing chunk size, top-k, the system prompt, the base
model, or `DISCUSSION_DISTANCE_PENALTY` (see Known limitations) to catch
regressions.

## Project layout

```
data/
  rfcs/raw/                RFC-editor originals (207 files)
  rfcs/clean/               boilerplate-stripped
  vendor_docs/               vendor doc originals (664 files, 11 products)
  vendor_docs_clean/         normalized to plain text with '#' headings
  chunks/chunks.jsonl        unified, section-aware chunks ready for embedding
  chunks/discussions_chunks.jsonl   mailing-list chunks (separate file)
  index/                      LanceDB vector index for RFCs+vendor docs (file-based, no server)
  index_discussions/           separate LanceDB index for mailing-list chunks
  discussions/                  raw .eml/.mbox.gz archives (ietf dnsop/dns-privacy/dd,
                                 dns-oarc, ripe dns-wg)
  discussions_clean/            parsed + cleaned messages, one JSONL per list
  eval/                          eval sets + generated reports (RFC/vendor + discussions)
dns_expert/                retrieval + CLI Python package
scripts/                    pipeline stages + setup.sh + eval runners
Modelfile                   DNS-expert system prompt, layered on qwen2.5:32b-instruct
bin/dns-expert               entry point
```

## Known limitations / next steps

- **Mailing list archives unused.** `data/discussions/` (ietf dnsop/dns-privacy,
  dns-oarc, ripe dns-wg — ~300MB) is downloaded but intentionally excluded from
  the pipeline for now. It's noisier than RFCs/vendor docs and would need
  filtering for signal before indexing.
- **Fixed: a lossy ANN vector index was silently degrading retrieval.**
  `build_index.py` used to attempt an IVF_PQ approximate-nearest-neighbor
  index, on the assumption it would fail to build at this corpus size
  (~12k rows) and fall back to exact brute-force search. It didn't fail —
  it built anyway, badly under-sized (too few rows per partition for
  accurate quantization). Concretely, a true nearest-neighbor chunk at
  cosine distance 0.30 (should rank ~top-3) was ranked **#219** by the
  approximate index. Root-caused by comparing LanceDB's reported distance
  against a manually-computed cosine distance on the same vectors — they
  didn't match, which pointed straight at the index. Fixed by dropping the
  index and removing the `create_index()` call from `build_index.py`
  entirely: at this scale, brute-force cosine search is both exact and
  fast (<1s). This alone fixed `tlsa-rr-type-code` (RFC 6698 now retrieves
  correctly) and improved `wildcard-matching-terms`'s retrieval (now
  retrieves RFC 4592 correctly; the remaining miss there is the model not
  using the exact terms "closest encloser"/"source of synthesis" from an
  already-correctly-retrieved chunk — a generation-precision issue, not
  retrieval).
- **`also-notify`/`only-notify` case: two fixes tried, case improved but not
  closed.** Asked for PowerDNS Authoritative's `also-notify` setting (as
  both a plain QA question and a config-generation task), the model answers
  from the similarly-named `only-notify` setting instead, and in doing so
  actually *misreads* what `only-notify` does (a whitelist-with-exclusions
  filter) as if it were a way to add extra notify targets — so this isn't
  pure name confusion, it's the model over-interpreting the one directive
  it does have in context because the one it needs isn't there.
  Two fixes were shipped for this:
  1. **`Modelfile` guardrail** — added an explicit instruction not to
     present a similarly-named setting as the one asked about when the
     actual one isn't in context. Didn't fully catch this case, because the
     failure mode here is subtler than name-swapping (see above).
  2. **`scripts/enrich_chunks.py`** — a new pipeline stage that generates a
     one-sentence natural-language paraphrase (via a fast local model,
     `lfm2.5:8b`) for ~1,200 short/terse vendor-doc chunks (config directive
     references etc.), inserted into the chunk text before embedding, so
     retrieval aligns better with how users phrase questions rather than
     matching the terse original doc wording. This measurably helped:
     `also-notify`'s rank for the eval's exact question improved from
     **#122 → #72** out of ~800 pdns-auth chunks — but that's still outside
     the top-8 retrieved, so the chunk still doesn't make it into context
     for this specific question, beaten by long narrative docs (FAQ,
     security advisories) that share surface vocabulary with "NOTIFY" but
     aren't the actual answer. Full eval re-run after both fixes: no
     regressions anywhere (still 42/42 retrieval), same 3 keyword misses as
     before.
  Next thing to try if this specific case matters in practice: reranking
  (retrieve a wider top-30-50 candidate pool, then have the local model or
  a cross-encoder re-score them for true relevance before picking the final
  top-8) — the standard IR fix for exactly this "embedding similarity ≠
  true relevance" gap, not yet implemented.
- **Negative-case (should-decline) handling is solid** once the eval
  harness's hedge-phrase list was fixed (`scripts/run_eval.py`) — the model
  was already correctly declining to answer fabricated/unanswerable
  questions ("the provided context does not contain...") in all 7 cases; an
  early version of the phrase-matching heuristic just didn't recognize that
  wording and under-reported it as failures.
- **Config-generation can still misplace directives** even when retrieval
  succeeds (e.g. putting an option in the wrong config block) — this is a
  generation issue, not a retrieval issue. Worth periodically eyeballing
  `config-*` cases in the eval report, and expanding the eval set as new gaps
  are found.
- **No syntax validation of generated configs.** Installing the actual server
  binaries (or their `-checkconf` style tools) and running generated configs
  through them would catch syntax errors the keyword-based eval can't.
- **Fine-tuning is optional and not yet needed.** Given the current eval
  results, a LoRA fine-tune (for style/format, not facts) is a nice-to-have,
  not a requirement — revisit only if RAG-only answers prove insufficient in
  practice.

### Mailing list archives

`data/discussions/` (ietf dnsop/dns-privacy/dd, DNS-OARC dns-operations, RIPE
DNS WG — ~300MB raw, 27,566 messages spanning 2016-2026) is now indexed and
on by default (`--no-discussions` to turn it off). Built as a fully separate
pipeline and index (`data/discussions_clean/`, `data/chunks/discussions_chunks.jsonl`,
`data/index_discussions/`) so it's reversible with zero effect on the
RFC/vendor index — see `dns_expert/retrieval.py`'s `INCLUDE_DISCUSSIONS_DEFAULT`.

- **Noise filtering is heuristic, not exhaustive.** `scripts/parse_discussions.py`
  drops known auto-generated bot messages (New Version Notification, I-D
  Action, WG/Document/Protocol Action) and replies under 150 characters after
  quote-stripping (89% of raw messages kept — 27,566 → 24,641 pre-chunk,
  31,576 after the dns-oarc fix below). Procedural chatter that doesn't match
  those patterns (e.g. a WG-adoption notice from "IETF Secretariat" with an
  atypical subject line) can still slip through. Not chased further since it
  doesn't produce misleading content, just occasional low-value chunks.
- **Thread reconstruction is simplified.** Rather than building a full
  reply-graph from `In-Reply-To`/`References` headers, citation grouping uses
  normalized subject lines (stripping `Re:`/`Fwd:`/`[listname]` prefixes).
  Good enough for citation and topic grouping; a full graph would be needed
  for anything that requires reconstructing exact reply order within a thread.
- **One real bug caught during ingestion:** `dns-oarc-dns-operations` archives
  are gzipped mbox-format monthly digests (`.txt.gz`), not individual `.eml`
  files like the other lists. The first parse pass treated them as raw `.eml`
  and produced garbage (binary mojibake chunks, e.g. one hit 133KB of noise;
  message count was a suspicious flat 120 — one "message" per digest file).
  Fixed by routing that list through the same mbox parser as `ripe-dns-wg`;
  correctly yields 8,043 real messages instead.
- **Mixing a second index changed the ranking dynamics of the first.**
  Turning discussions on by default (merging both indexes' results by raw
  cosine distance — valid since both use the same embedding model) caused
  one RFC/vendor eval case to regress: RFC 8484 (the actual DNS-over-HTTPS
  RFC) lost its top-8 slot to a discussion chunk by a 0.0003 distance margin
  — a near-tie, not a real relevance gap. Fixed with a small
  `DISCUSSION_DISTANCE_PENALTY` (0.01) added to discussion results before
  the merge-and-sort, so RFC/vendor content wins close ties while genuinely
  more-relevant discussion content (larger margins) still surfaces normally.
  Verified: main eval back to the exact pre-discussions baseline (42/42/39/42/39/42/7/7),
  discussions eval unaffected (12/12/11/12/11/12/3/3).
- **Trust framing lives in the `Modelfile`**, not just this doc: mailing list
  excerpts are instructed to be attributed to the person/date and never
  presented as settled consensus, since (unlike RFCs/vendor docs) they're
  individual opinions and debate, not normative specification.
