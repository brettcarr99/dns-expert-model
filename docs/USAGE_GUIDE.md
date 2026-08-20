# DNS-Expert: User Manual & Operational Guide

This guide covers all operating modes, slash commands, diagnostic pipe workflows, and practical examples for DNS engineers.

---

## 1. Operating Modes

DNS-Expert supports three primary invocation modes:

```bash
# 1. Interactive REPL Chat
dns-expert

# 2. Direct Single-Shot CLI Query
dns-expert ask "Explain DNS cookies and how they mitigate spoofing attacks"

# 3. Diagnostic Stdin Pipe Mode
dig +dnssec example.com @8.8.8.8 | dns-expert debug "Why is this query returning SERVFAIL?"
```

---

## 2. Interactive REPL Mode

Starting `dns-expert` with no arguments launches the interactive terminal interface:

```text
  ____  _   _ ____    _____                      _   
 |  _ \| \ | / ___|  | ____|_  ___ __   ___ _ __| |_ 
 | | | |  \| \___ \  |  _| \ \/ / '_ \ / _ \ '__| __|
 | |_| | |\  |___) | | |___ >  <| |_) |  __/ |  | |_ 
 |____/|_| \_|____/  |_____/_/\_\ .__/ \___|_|   \__|
                                |_|                  
 [v1.0.0] Local DNS Engineering Assistant (Model: dns-expert)
 Type /help for commands, /quit to exit.

dns-expert> How do I configure QNAME minimisation in Unbound?
```

### Slash Commands in REPL

| Slash Command | Description | Example |
| :--- | :--- | :--- |
| **`/rfc <num>`** | Query specific RFC details and requirements | `/rfc 8484`, `/rfc 1035`, `/rfc 4034` |
| **`/vendor <name>`** | Restrict retrieval knowledge to a specific vendor | `/vendor bind9`, `/vendor unbound`, `/vendor powerdns` |
| **`/vendor all`** | Clear vendor filters and search all sources | `/vendor all` |
| **`/sources`** | Display source documents and citation table for last response | `/sources` |
| **`/stats`** | Show indexed chunk counts, source breakdown, and DB size | `/stats` |
| **`/model <name>`** | Switch active Ollama model | `/model llama3.1:8b`, `/model qwen2.5:7b` |
| **`/clear`** | Reset conversation context and history | `/clear` |
| **`/help`** | Display command reference | `/help` |
| **`/quit`** or **`/exit`** | Exit the application | `/quit` |

---

## 3. Command Line Subcommands

### 1. `dns-expert ask <query>`
Runs a single query and prints the response with rich markdown formatting:
```bash
dns-expert ask "What are the standard TTL recommendations for DNS root and TLD zones?" --citations
```

### 2. `dns-expert debug [optional query]`
Reads input from `stdin` and provides automated root-cause analysis:

```bash
# Debug live dig output
dig +dnssec fail01.dnssec.works @1.1.1.1 | dns-expert debug

# Audit BIND configuration
cat /etc/bind/named.conf.options | dns-expert debug "Audit this configuration for security and recursion risks"

# Validate zone file syntax
cat /var/named/example.com.zone | dns-expert debug "Check for apex CNAME violations or missing glue records"
```

### 3. `dns-expert rfc <number>`
Directly summarizes key sections and technical specifications for any DNS RFC:
```bash
dns-expert rfc 7873
dns-expert rfc 9460
```

### 4. `dns-expert stats`
Prints knowledge base statistics:
```bash
dns-expert stats
```

---

## 4. Practical Workflows & Scenarios

### Scenario A: Configuring Response Policy Zones (RPZ) in BIND 9
```text
dns-expert[bind9]> How do I configure a response policy zone for malware blocking in named.conf?
```
**Output Highlights**:
- Syntactically valid `response-policy { zone "rpz.local"; };` configuration block.
- Zone statement with `type master;` or `type slave;`.
- Explanation of RPZ action triggers (QNAME, IP, Client-IP, NSIP, NSDNAME).
- Grounded in BIND 9 Administrator Reference Manual (ARM).

---

### Scenario B: Diagnosing DNSSEC Validation Breakage
```bash
delv +multiline +vtrace example.com | dns-expert debug
```
**Output Highlights**:
- Parses `delv` trace output step-by-step (Root -> TLD -> Domain).
- Identifies missing DS records, algorithm mismatch, or expired RRSIG signatures.
- References RFC 4035 (Section 5: Resolver Validation Logic).

---

### Scenario C: Designing an Anycast DNS Architecture
```text
dns-expert> What are the BGP Anycast routing best practices for authoritative DNS clusters across multiple data centers?
```
**Output Highlights**:
- Recommendations on BGP AS-PATH prepending and community tagging.
- Handling TCP session persistence and Path MTU Discovery issues (RFC 7766).
- Recommendations from RIPE DNS-WG and DNS-OARC operational mailing lists.

---

### Scenario D: Filtering by Specific Vendor Docs
```text
dns-expert> /vendor coredns
[+] Knowledge retrieval restricted to: COREDNS
dns-expert[coredns]> How do I configure DNS-over-TLS (DoT) upstream forwarding with TLS verification?
```
