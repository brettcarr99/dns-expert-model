"""Configuration settings and environment defaults for DNS-Expert."""

import os
from pathlib import Path

# Base Paths
DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
USER_HOME = Path.home()
DEFAULT_DATA_DIR = USER_HOME / ".dns-expert"

# Database Location
# Priority: DNS_EXPERT_DB env -> workspace dns_knowledge.db -> ~/.dns-expert/dns_knowledge.db
_env_db = os.environ.get("DNS_EXPERT_DB")
if _env_db:
    DB_PATH = Path(_env_db)
elif (DEFAULT_WORKSPACE_ROOT / "dns_knowledge.db").exists():
    DB_PATH = DEFAULT_WORKSPACE_ROOT / "dns_knowledge.db"
else:
    DB_PATH = DEFAULT_DATA_DIR / "dns_knowledge.db"

# Ollama Settings
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("DNS_EXPERT_MODEL", "dns-expert")
FALLBACK_CHAT_MODELS = ["dns-expert", "llama3.1:8b", "qwen2.5:7b", "qwen2.5:14b", "mistral:7b"]
EMBED_MODEL = os.environ.get("DNS_EXPERT_EMBED_MODEL", "nomic-embed-text")

# RAG & Search Parameters
DEFAULT_TOP_K = int(os.environ.get("DNS_EXPERT_TOP_K", "6"))
RRF_K_CONSTANT = 60  # Reciprocal Rank Fusion constant
MAX_CONTEXT_TOKENS = 6000
EMBEDDING_DIM = 768

# Supported Vendors
SUPPORTED_VENDORS = [
    "bind9",
    "coredns",
    "dnsdist",
    "dnsmasq",
    "knot-dns",
    "knot-resolver",
    "nsd",
    "pdns-auth",
    "pdns-recursor",
    "technitium",
    "unbound",
]
