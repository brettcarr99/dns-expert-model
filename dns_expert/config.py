"""Configuration settings and environment defaults for DNS-Expert."""

import os
from pathlib import Path

# Base Paths
DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
USER_HOME = Path.home()
DEFAULT_DATA_DIR = USER_HOME / ".dns-expert"

# Database and Encrypted Container Location
# Priority: DNS_EXPERT_DB env -> workspace dns_knowledge.db -> ~/.dns-expert/dns_knowledge.db
_env_db = os.environ.get("DNS_EXPERT_DB")
if _env_db:
    DB_PATH = Path(_env_db)
elif (DEFAULT_WORKSPACE_ROOT / "dns_knowledge.db").exists():
    DB_PATH = DEFAULT_WORKSPACE_ROOT / "dns_knowledge.db"
else:
    DB_PATH = DEFAULT_DATA_DIR / "dns_knowledge.db"

# Encrypted container path
ENCRYPTED_BLOB_PATH = DEFAULT_WORKSPACE_ROOT / "dns_knowledge.dat"
USER_BLOB_PATH = DEFAULT_DATA_DIR / "dns_knowledge.dat"

# Ollama Settings
# Sanitise OLLAMA_HOST: the env var is also used by the Ollama *server* as a
# listen address (e.g. "0.0.0.0:11434"), which is not a valid client URL.
# If the value lacks a scheme we normalise it to a proper http:// URL, falling
# back to localhost if the raw value is unusable (bare "0.0.0.0", empty, etc.).
def _resolve_ollama_host() -> str:
    raw = os.environ.get("OLLAMA_HOST", "").strip()
    if not raw:
        return "http://127.0.0.1:11434"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    # Bare host or host:port (e.g. "0.0.0.0:11434", "192.168.1.1:11434")
    # "0.0.0.0" is a listen-all bind address — meaningless for a client; use localhost.
    host_part = raw.split(":")[0]
    if host_part in ("0.0.0.0", ""):
        return "http://127.0.0.1:11434"
    return f"http://{raw}"

OLLAMA_HOST = _resolve_ollama_host()
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
