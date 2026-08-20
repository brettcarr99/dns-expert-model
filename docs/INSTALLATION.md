# DNS-Expert: Installation & Deployment Guide

This guide covers installing and running **DNS-Expert** on local workstations and servers.

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
| :--- | :--- | :--- |
| **Operating System** | macOS 12+ (Apple Silicon or Intel), Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+, Arch) | macOS (Apple Silicon M1/M2/M3/M4) or Linux x86_64 with NVIDIA GPU / modern CPU |
| **System Memory (RAM)**| **8 GB** (using compact 3B model or CPU offload) | **16 GB** (runs full 8B model + embeddings + vectors with >8GB free) |
| **Storage** | 8 GB free disk space | 15 GB free SSD space |
| **Python** | Python 3.9+ | Python 3.10, 3.11, 3.12, 3.13, 3.14 |
| **Ollama** | Ollama 0.3.0+ | Latest Ollama release |

---

## 2. Automated 1-Step Installation (Recommended)

The automated `install.sh` script verifies prerequisites, starts Ollama, downloads models, sets up the custom `dns-expert` Modelfile, and links the CLI executable.

```bash
# 1. Clone the repository
git clone https://github.com/dns-experts/dns-expert.git
cd dns-expert

# 2. Run the installer
./install.sh
```

### What `install.sh` Performs:
1. Verifies Python 3.9+ is installed.
2. Checks for Ollama and starts the background daemon if needed (`ollama serve`).
3. Downloads the embedding model (`ollama pull nomic-embed-text`).
4. Downloads the base LLM (`ollama pull llama3.1:8b` or `qwen2.5:7b`).
5. Builds the customized `dns-expert` model in Ollama (`ollama create dns-expert -f Modelfile`).
6. Creates a Python virtual environment (`.venv`) and installs `dns-expert`.
7. Copies the pre-bundled `dns_knowledge.db` to `~/.dns-expert/dns_knowledge.db`.
8. Creates an executable symlink in `~/.local/bin/dns-expert`.

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

### Step 5: Verify Knowledge Base
If `dns_knowledge.db` is already in the project root:
```bash
# Check stats
dns-expert stats
```

---

## 4. Environment Variables & Configuration

You can customize runtime behavior using environment variables in your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Custom Ollama Host / Port (default: http://127.0.0.1:11434)
export OLLAMA_HOST="http://127.0.0.1:11434"

# Override default LLM (e.g. use qwen2.5:7b or llama3.1:8b)
export DNS_EXPERT_MODEL="dns-expert"

# Override embedding model
export DNS_EXPERT_EMBED_MODEL="nomic-embed-text"

# Custom knowledge database path
export DNS_EXPERT_DB="/path/to/my_custom_dns_knowledge.db"

# Number of retrieved knowledge chunks (default: 6)
export DNS_EXPERT_TOP_K=8
```

---

## 5. Offline & Air-Gapped Deployment

For secure operational environments without internet access:

1. **On an internet-connected machine**:
   ```bash
   # Export Ollama models
   ollama pull nomic-embed-text
   ollama pull llama3.1:8b
   ollama create dns-expert -f Modelfile

   # Bundle the project directory including .venv and dns_knowledge.db
   tar -czvf dns-expert-offline.tar.gz dns-expert/ ~/.ollama/models/
   ```

2. **On the air-gapped machine**:
   ```bash
   tar -xzvf dns-expert-offline.tar.gz
   cp -r models/* ~/.ollama/models/
   cd dns-expert
   ./install.sh
   ```

---

## 6. Troubleshooting Common Installation Issues

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

### 3. High memory usage or slow token generation
**Resolution**:
If your machine has less than 16GB RAM, switch to a smaller quantized model:
```bash
ollama pull llama3.2:3b
dns-expert --model llama3.2:3b
```
