# DNS-Expert: Installation & Deployment Guide

This guide covers installing and running **DNS-Expert** on local workstations and servers.

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
| :--- | :--- | :--- |
| **Operating System** | macOS 12+ (Apple Silicon or Intel), Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+, Arch) | macOS (Apple Silicon M1/M2/M3/M4) or Linux x86_64 with NVIDIA GPU / modern CPU |
| **System Memory (RAM)**| **8 GB** (using compact 3B model or CPU offload) | **16 GB** (runs full 8B model + embeddings + vectors with >8GB free) |
| **Storage** | 8 GB free disk space | 15 GB free SSD space |
| **Python** | Python 3.9+ | Python 3.10, 3.11, 3.12, 3.13 |
| **Ollama** | Ollama 0.3.0+ | Latest Ollama release |

---

## 2. Automated 1-Step Installation (Recommended)

The automated `install.sh` script verifies prerequisites, starts Ollama, downloads models, sets up the custom `dns-expert` Modelfile, downloads the encrypted knowledge vault, and links the CLI executable.

```bash
# 1. Clone the repository
git clone https://github.com/brettcarr99/dns-expert-model.git
cd dns-expert-model

# 2. Run the installer
./install.sh
```

### What `install.sh` Performs

| Phase | Step | Detail |
| :--- | :--- | :--- |
| 1 | Pre-flight checks | Verifies OS, RAM (selects 3B or 8B model profile), disk space, hardware acceleration, and required CLI utilities |
| 2 | Python runtime | Confirms Python 3.9+ |
| 3 | Ollama daemon | Checks for Ollama, installs it if missing, ensures `ollama serve` is running |
| 4 | Pull models | `ollama pull nomic-embed-text` (~274 MB) + base LLM (`llama3.1:8b` ~4.7 GB or `llama3.2:3b` for <8 GB RAM) |
| 5 | Custom model | `ollama create dns-expert -f Modelfile` — registers the DNS-tuned persona and inference parameters |
| 6 | Python venv | Creates `.venv`, installs the `dns-expert` package and its dependencies |
| 7 | Knowledge vault | Downloads the AES-256 encrypted knowledge vault (`dns_knowledge.dat`, ~40 MB) from the [GitHub Release](https://github.com/brettcarr99/dns-expert-model/releases/latest) if not already present, then decrypts it to `~/.dns-expert/dns_knowledge.db` |
| 7 | CLI executable | Creates `~/.local/bin/dns-expert` wrapper pointing at the venv |

> **Note**: The knowledge vault is not bundled in the repository (see [§6 — Knowledge Vault Distribution](#6-knowledge-vault-distribution)). It is downloaded automatically by `install.sh`. If you are on a slow connection the ~40 MB download is the longest step.

---

## 3. Manual Step-by-Step Installation

If you prefer to configure everything manually or customize installation paths:

### Step 1: Install Ollama
- **macOS**: Download from [ollama.com/download/mac](https://ollama.com/download/mac) or `brew install ollama`
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`

Start the Ollama service:
```bash
ollama serve &
```

### Step 2: Pull Required Models
```bash
# Embedding model for vector retrieval (274 MB)
ollama pull nomic-embed-text

# Base LLM (4.7 GB)
ollama pull llama3.1:8b
```

### Step 3: Create Custom DNS-Expert Model
```bash
ollama create dns-expert -f Modelfile
```

### Step 4: Install Python Package
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and dns-expert
pip install --upgrade pip
pip install -e .
```

### Step 5: Download and Decrypt Knowledge Vault
```bash
# Download the encrypted knowledge vault from GitHub Releases
mkdir -p ~/.dns-expert
curl -fL -o ~/.dns-expert/dns_knowledge.dat \
  https://github.com/brettcarr99/dns-expert-model/releases/latest/download/dns_knowledge.dat

# Decrypt it (uses the dns-expert package installed in step 4)
python3 -c "
from pathlib import Path
from dns_expert.knowledge.crypto import decrypt_file
decrypt_file(
    Path('$HOME/.dns-expert/dns_knowledge.dat'),
    Path('$HOME/.dns-expert/dns_knowledge.db')
)
print('Knowledge vault ready.')
"
```

### Step 6: Verify Installation
```bash
dns-expert stats
```

---

## 4. Environment Variables & Configuration

You can customize runtime behavior using environment variables in your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Custom Ollama Host / Port (default: http://127.0.0.1:11434)
export OLLAMA_HOST="http://127.0.0.1:11434"

# Override default LLM (e.g. use qwen2.5:7b or llama3.1:8b directly)
export DNS_EXPERT_MODEL="dns-expert"

# Override embedding model
export DNS_EXPERT_EMBED_MODEL="nomic-embed-text"

# Custom knowledge database path (useful for multiple corpus versions)
export DNS_EXPERT_DB="/path/to/my_custom_dns_knowledge.db"

# Number of retrieved knowledge chunks per query (default: 6)
export DNS_EXPERT_TOP_K=8
```

---

## 5. Offline & Air-Gapped Deployment

For secure operational environments without internet access, all components must be pre-staged on an internet-connected machine and transferred manually.

### Stage on an internet-connected machine:
```bash
# 1. Pull Ollama models
ollama pull nomic-embed-text
ollama pull llama3.1:8b
ollama create dns-expert -f Modelfile

# 2. Download the knowledge vault
mkdir -p ~/.dns-expert
curl -fL -o ~/.dns-expert/dns_knowledge.dat \
  https://github.com/brettcarr99/dns-expert-model/releases/latest/download/dns_knowledge.dat

# 3. Bundle everything for transfer
tar -czvf dns-expert-offline.tar.gz \
  dns-expert-model/ \
  ~/.dns-expert/dns_knowledge.dat \
  ~/.ollama/models/
```

### Deploy on the air-gapped machine:
```bash
# Transfer dns-expert-offline.tar.gz via USB / SCP / approved channel, then:
tar -xzvf dns-expert-offline.tar.gz
cp -r models/ ~/.ollama/models/
cp dns_knowledge.dat ~/.dns-expert/

# install.sh detects the local dns_knowledge.dat and skips the download
cd dns-expert-model
./install.sh
```

> `install.sh` checks for `~/.dns-expert/dns_knowledge.dat` before attempting a network download; placing the file there manually is all that is needed for air-gapped installs.

---

## 6. Knowledge Vault Distribution

The compiled knowledge vault (`dns_knowledge.dat`) is **not stored in the git repository**. It is distributed as a [GitHub Release asset](https://github.com/brettcarr99/dns-expert-model/releases/latest) for the following reasons:

| Reason | Detail |
| :--- | :--- |
| **Repository size** | At ~40 MB (compressed), committing the vault would bloat every clone; it will grow with each corpus update |
| **Independent versioning** | The vault can be updated independently of the Python source code — a corpus refresh does not require a code release |
| **Git history cleanliness** | Binary blobs in git history are permanent and cannot be efficiently delta-compressed |

The vault is an AES-256 encrypted, zlib-compressed binary container. See [ARCHITECTURE.md §6](ARCHITECTURE.md#6-security-privacy--knowledge-vault-distribution) for the full encryption and distribution model.

---

## 7. Troubleshooting Common Installation Issues

### 1. `Connection refused` when connecting to Ollama
**Symptom**: `Could not connect to Ollama at http://127.0.0.1:11434`
**Resolution**:
```bash
# Start Ollama service
ollama serve &
# Check listening status
curl http://127.0.0.1:11434/api/tags
```

### 2. `dns-expert: command not found`
**Symptom**: The binary is installed but not found in current shell.
**Resolution**: Add `~/.local/bin` to your `$PATH`:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 3. Knowledge vault download fails
**Symptom**: `curl: (22) The requested URL returned error: 404` or network timeout.
**Resolution**: Download manually and place at the expected path:
```bash
# Download from browser: https://github.com/brettcarr99/dns-expert-model/releases/latest
# Then:
mkdir -p ~/.dns-expert
mv ~/Downloads/dns_knowledge.dat ~/.dns-expert/
# Re-run install.sh — it will detect the local file and skip the download
./install.sh
```

### 4. High memory usage or slow token generation
**Resolution**:
If your machine has less than 16 GB RAM, switch to a smaller quantized model:
```bash
ollama pull llama3.2:3b
dns-expert --model llama3.2:3b
```
