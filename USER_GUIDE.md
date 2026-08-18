# DNS Expert — Getting Started (for DNS engineers, no AI background required)

This is a chat assistant that specializes in DNS: the protocol itself, DNSSEC,
troubleshooting, and writing configuration for ten different DNS server
products (BIND9, PowerDNS, dnsdist, Knot DNS, Knot Resolver, Unbound, NSD,
CoreDNS, dnsmasq, Technitium).

You don't need to know anything about AI to use it. This guide assumes you
know DNS, not machine learning.

## What makes this different from just asking ChatGPT

Two things:

1. **It runs entirely on your own machine.** Nothing you type gets sent
   anywhere over the internet. No account, no API key, no cloud service.
2. **It looks things up before answering, instead of relying on memory.**
   Before every answer, it searches a local library of ~200 DNS-related RFCs,
   the official documentation for all ten server products, and a decade of
   IETF/DNS-OARC/RIPE mailing list discussion, pulls the relevant passages,
   and bases its answer on those — citing exactly which RFC section, doc
   page, or mailing list post it used. This matters because plain chatbots
   frequently get exact syntax, default values, and RFC details wrong; this
   one is built specifically to reduce that.

## What you can use it for

- **"What does the spec actually say?"** — e.g. "What's the maximum TTL a DNS
  record can have?", "What port does DNS-over-TLS use?", "What's the DNSSEC
  algorithm number for ECDSA P-256?"
- **"How do I configure X in [server]?"** — e.g. "How do I enable DNSSEC
  validation in Unbound?", "What BIND9 statement configures response rate
  limiting?"
- **"Write me a config for..."** — e.g. "Write a BIND9 zone block for a
  secondary zone example.com transferring from 192.0.2.1", "Write a dnsdist
  config that load-balances across two backend servers." It will produce a
  complete, ready-to-edit config file with the security-relevant defaults
  called out (ACLs, DNSSEC validation, rate limiting).
- **Troubleshooting and "why would this happen"** questions grounded in the
  actual protocol behavior.
- **Comparing how different servers handle the same thing** — e.g. "How does
  zone-transfer ACL syntax differ between BIND9 and Knot DNS?"
- **"What was the argument about X in the DNS community?"** — e.g. "What
  concerns were raised about QNAME minimization on the IETF dnsop list?",
  "Who's argued against wide adoption of DNS-over-HTTPS, and why?" It can
  pull up specific mailing list threads, name who said what and when, and
  summarize a debate — but see the note on trusting this below.

## What it's not good for

- Anything outside DNS — it has no special knowledge of your network, your
  cloud provider, or general sysadmin topics.
- Extremely obscure, undocumented internals (e.g. "what's the hard-coded
  buffer size in dnsdist's source code") — if it's not in the RFCs or the
  vendor docs, the assistant is instructed to tell you it doesn't know rather
  than guess. That's intentional — treat "I don't have that in the provided
  documentation" as a real, useful answer, not a failure.
- Company-specific or environment-specific config — it doesn't know your
  actual infrastructure. Treat generated configs as a correct *starting
  point* to adapt, not something to paste into production unread.
- **Treating mailing list opinions as official policy.** RFCs and vendor
  docs are normative; mailing list posts are individual engineers arguing,
  proposing, and disagreeing at a point in time. It's instructed to
  attribute mailing list claims to the person and date rather than
  presenting them as settled fact, and to say plainly if you ask what a
  working group "decided" and the retrieved posts only show discussion, not
  a decision — but always read who said it before treating it as consensus.

## One-time setup

You need two things installed: **Ollama** (the program that runs the AI
model on your machine) and **Python 3.10+** (almost certainly already on
your Mac/Linux box — check with `python3 --version` in a terminal).

1. Install Ollama from **https://ollama.com** (download, open the installer,
   follow the prompts — same as installing any desktop app).
2. Open a terminal, go to this project folder, and run the setup script:

   ```bash
   cd path/to/dns-expert-model
   ./scripts/setup.sh
   ```

   This will take a while the first time (it's downloading a ~19GB AI model
   and building a searchable index out of all the RFCs and vendor docs —
   expect 20-40 minutes depending on your internet connection). You'll see
   progress messages the whole way; it's safe to walk away and come back. It
   needs about 25GB of free disk space.

3. When it says "Setup complete," you're done and can start using it — see
   *Everyday use* below. You won't need to repeat this step again unless you
   delete the project or want to refresh the corpus.

4. **Optional, and much slower:** if you also want it to answer questions
   about a decade of IETF/DNS-OARC/RIPE mailing list discussion (not just
   RFCs and vendor docs), run:

   ```bash
   ./scripts/setup_discussions.sh
   ```

   This is a genuinely long process — it downloads mailing list archives at
   a deliberately slow, polite pace so it doesn't hammer the IETF's mail
   server, and can realistically take **10+ hours** for the largest list
   alone. Kick it off before you go to bed, or just skip it — everything in
   this guide works fine without it, and `dns-expert` quietly falls back to
   RFCs + vendor docs only until this step has been run.

## Everyday use

**Ask a single question and get an answer:**

```bash
./bin/dns-expert "How do I enable DNSSEC validation in Unbound?"
```

**Have an ongoing conversation** (it remembers earlier turns, so you can ask
follow-ups like "now show me the same thing for BIND9"):

```bash
./bin/dns-expert
```

This drops you into a `You:` prompt. Type your question, hit enter, read the
answer, keep going. Type `exit` or press Ctrl-D to leave.

**See what it looked up before answering** (useful if an answer seems off,
or you're just curious): add `-v`:

```bash
./bin/dns-expert -v "What TCP port does DNS-over-HTTPS use?"
```

This prints the RFC/doc sections it retrieved before generating the answer,
so you can sanity-check the sources yourself.

## How to get good answers

- **Name the server software** if you're asking a config question — "how do
  I do X" is ambiguous across ten products; "how do I do X in PowerDNS
  Recursor" isn't.
- **State the specifics** for config-generation requests: IP addresses, zone
  names, which role (primary/secondary), etc. The more concrete your ask,
  the more directly usable the output.
- **Check the citation.** Every factual claim should come with something
  like `(RFC 7858 §3.1)` or `(bind9 arm, dnssec.rst)`. If you see a specific
  number or default value with no citation attached, treat it as the model's
  general background knowledge, not something it verified against the docs
  — worth double-checking yourself if it matters.
- **If it says it doesn't know, believe it** rather than pushing for an
  answer — that's the intended behavior when the topic isn't covered in the
  RFCs/vendor docs it has access to, and it's specifically designed not to
  make things up in that situation.

## Troubleshooting

- **`ollama: command not found`** — Ollama isn't installed or isn't on your
  PATH; reinstall from ollama.com and restart your terminal.
- **Setup hangs or fails partway through** — safe to just re-run
  `./scripts/setup.sh` again; every step skips work it's already done and
  picks up where it left off.
- **Answers are slow (many seconds per response)** — normal on a laptop
  without a lot of memory; the model is large. It'll still be far faster
  than reading through raw RFCs by hand.
- **"model not found" error** — setup didn't finish; re-run
  `./scripts/setup.sh`.

## Where the knowledge comes from

Everything it can cite comes from:
- ~200 DNS-relevant RFCs (official protocol specifications)
- Official documentation for BIND9, PowerDNS (Authoritative + Recursor),
  dnsdist, Knot DNS, Knot Resolver, Unbound, NSD, CoreDNS, dnsmasq, and
  Technitium
- A decade (2016-2026) of IETF dnsop/dns-privacy/dd, DNS-OARC
  dns-operations, and RIPE DNS WG mailing list discussion — *if* you've run
  `./scripts/setup_discussions.sh` (see One-time setup above; it's optional
  and slow, so this may not be built yet on a fresh install). See the note
  under "What it's not good for" above on how to read mailing list
  citations — they're opinions and debate, not settled fact.

## Want more technical detail?

See `README.md` in this folder for how the system is actually built
(chunking, embeddings, the vector index, the eval harness) and its current
known limitations.
