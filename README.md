# DNS-Expert 🛰️

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Ollama](https://img.shields.io/badge/runtime-Ollama-purple.svg)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**DNS-Expert** is an offline-capable, high-performance local AI assistant and retrieval system designed specifically for **DNS engineers, network operators, and protocol developers**.

It runs entirely on local hardware using **Ollama** within a strict **16GB RAM budget**, integrating a pre-indexed embedded knowledge base of all DNS RFCs, major DNS software documentation (BIND 9, PowerDNS, Knot, Unbound, NSD, CoreDNS, dnsdist, etc.), and a decade of DNS mailing list archives.

---

## 🚀 Quick Start (1-Step Install)

```bash
# Clone the repository
git clone https://github.com/brettcarr99/dns-expert-model.git
cd dns-expert-model

# Run the automated installer
# (downloads the ~40 MB encrypted knowledge vault from GitHub Releases automatically)
./install.sh
```

Then launch the assistant from your terminal:
```bash
# Interactive Chat REPL
dns-expert

# Direct Question
dns-expert ask "How do I configure QNAME minimisation in Unbound?"

# Pipe live dig or config files
dig +dnssec example.com @8.8.8.8 | dns-expert debug "Why is this returning SERVFAIL?"
```

---

## 🔍 Key Capabilities

1. **RFC Grounding**: Automatic retrieval across all DNS RFCs with section citations (RFC 1034/1035, DNSSEC, DoH, DoT, DoQ, SVCB/HTTPS, EDNS0, Cookies).
2. **Multi-Vendor Configuration**: Deep knowledge of BIND 9, PowerDNS (Auth & Recursor), Knot DNS & Knot Resolver, NSD, Unbound, CoreDNS, dnsdist, Technitium, and dnsmasq.
3. **Operational Diagnostics**: Pipe `dig`, `delv`, `kdig`, or config files directly into `dns-expert debug` for root-cause analysis.
4. **Hybrid Search (BM25 + Dense Vectors)**: Reciprocal Rank Fusion (RRF) guarantees exact keyword accuracy for RFC numbers and config directives combined with semantic conceptual matching.
5. **Memory-Conscious (< 16 GB RAM)**: Uses ~6.5 GB RAM total, leaving >8 GB free for your OS and development tools.
6. **100% Private & Air-Gapped**: Runs entirely on `localhost`. Zero data or telemetry sent externally.

---

## 🛠️ CLI & Slash Commands

Inside the interactive chat (`dns-expert`):
- `/rfc <num>` — Look up specific RFC requirements (e.g. `/rfc 8484`, `/rfc 1035`)
- `/vendor <name>` — Restrict retrieval to specific vendor docs (`/vendor bind9`, `/vendor unbound`, `/vendor powerdns`, etc.)
- `/vendor all` — Reset vendor filters
- `/sources` — View detailed citation sources and scores for the last response
- `/stats` — Show knowledge base statistics and indexed chunks
- `/model <name>` — Switch active Ollama model
- `/clear` — Reset conversation history
- `/help` — Display command reference
- `/quit` — Exit

---

## 📚 Documentation Suite

- [**System Architecture & Under-the-Hood Technical Specification**](docs/ARCHITECTURE.md): Deep-dive into chunking strategies, embedding generation, SQLite FTS5 + Dense Vector RRF math, and memory allocations.
- [**Installation & Deployment Guide**](docs/INSTALLATION.md): Complete setup walkthrough for macOS and Linux, custom model configurations, and air-gapped environments.
- [**User Manual & Operational Guide**](docs/USAGE_GUIDE.md): Detailed usage instructions, CLI options, and practical operational scenarios.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
