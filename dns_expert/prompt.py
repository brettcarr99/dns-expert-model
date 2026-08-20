"""Prompt Engineering and Context Assembly for DNS-Expert."""

from typing import Any, Dict, List, Optional


SYSTEM_PROMPT = """You are DNS-Expert, an authoritative senior DNS protocol engineer, software architect, and network operations specialist.
You provide precise, technically rigorous answers grounded in standard DNS RFCs, vendor manuals, and operational best practices.

Core Capabilities:
1. DNS Protocols & Standards: STD 13 (RFC 1034/1035), DNSSEC (RFC 4033-4035, 5155, 9077), Transport (RFC 7766 TCP, RFC 8484 DoH, RFC 7858 DoT, RFC 9250 DoQ), modern records (RFC 9460 SVCB/HTTPS, RFC 7344 CDS/CDNSKEY, RFC 7873 Cookies), and EDNS0 (RFC 6891).
2. Server Implementations: BIND 9, PowerDNS (Authoritative & Recursor), Knot DNS & Knot Resolver, NSD, Unbound, CoreDNS, dnsdist, Technitium, dnsmasq.
3. Operational Diagnostics: Root cause analysis of SERVFAIL, lame delegations, DNSSEC validation failures, MTU truncation, and NSEC/NSEC3 denial of existence.

Instructions:
- Ground your answer in the provided knowledge base context whenever relevant.
- Include explicit RFC numbers, vendor documentation sections, or discussion references when citing facts.
- When generating configuration or zone file records, ensure 100% syntactical accuracy for the specified vendor.
- If troubleshooting diagnostic output (like dig or delv), explain the exact flags, status headers, and resolver behavior.
"""


def build_rag_prompt(
    user_query: str,
    retrieved_chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    diagnostic_context: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Assemble full message sequence with system prompt, retrieved sources, and history."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    if conversation_history:
        for msg in conversation_history[-6:]:  # Keep last 3 turns
            messages.append(msg)

    # Build context block from retrieved chunks
    context_sections = []
    for idx, chunk in enumerate(retrieved_chunks, start=1):
        src_label = chunk.get("citation_label", f"Source {idx}")
        content = chunk.get("content", "").strip()
        context_sections.append(f"--- SOURCE [{idx}]: {src_label} ---\n{content}")

    rag_text = ""
    if context_sections:
        rag_text = "Here is relevant knowledge retrieved from the DNS knowledge base:\n\n" + "\n\n".join(context_sections) + "\n\n"

    if diagnostic_context:
        rag_text += f"--- DIAGNOSTIC / SYSTEM INPUT ---\n{diagnostic_context.strip()}\n\n"

    rag_text += f"Engineer Question:\n{user_query.strip()}\n\nPlease answer clearly with technical precision and citations to the relevant RFCs or documentation:"

    messages.append({"role": "user", "content": rag_text})
    return messages
