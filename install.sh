#!/usr/bin/env bash
# ==============================================================================
# DNS-Expert: Automated 1-Step Installation & Setup Script
# ==============================================================================
set -e

# Color helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
cat << "BANNER"
  ____  _   _ ____    _____                      _   
 |  _ \| \ | / ___|  | ____|_  ___ __   ___ _ __| |_ 
 | | | |  \| \___ \  |  _| \ \/ / '_ \ / _ \ '__| __|
 | |_| | |\  |___) | | |___ >  <| |_) |  __/ |  | |_ 
 |____/|_| \_|____/  |_____/_/\_\ .__/ \___|_|   \__|
                                |_|                  
BANNER
echo -e "${NC}"
echo -e "${BOLD}Local AI Knowledge Assistant for DNS Engineers & Developers${NC}\n"

# ==============================================================================
# PHASE 1: HARDWARE & SOFTWARE PRE-FLIGHT CHECKS
# ==============================================================================
echo -e "${CYAN}${BOLD}[1/7] Running Pre-Flight Hardware & Software System Checks...${NC}"

# --- 1A. Operating System & Architecture ---
OS_TYPE="$(uname -s)"
ARCH_TYPE="$(uname -m)"
echo -e "  ${DIM}• OS / Platform:${NC}      ${OS_TYPE} (${ARCH_TYPE})"

# --- 1B. Memory / RAM Verification ---
TOTAL_RAM_GB=0
if [ "$OS_TYPE" = "Darwin" ]; then
    MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    TOTAL_RAM_GB=$((MEM_BYTES / 1024 / 1024 / 1024))
elif [ "$OS_TYPE" = "Linux" ]; then
    if [ -f /proc/meminfo ]; then
        MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        TOTAL_RAM_GB=$((MEM_KB / 1024 / 1024))
    fi
fi

TARGET_MODEL="llama3.1:8b"
if [ "$TOTAL_RAM_GB" -ge 16 ]; then
    echo -e "  ${GREEN}✓${NC} ${DIM}System RAM:${NC}        ${BOLD}${TOTAL_RAM_GB} GB${NC} (Optimal for 8B model with >8GB headroom)"
elif [ "$TOTAL_RAM_GB" -ge 8 ]; then
    echo -e "  ${GREEN}✓${NC} ${DIM}System RAM:${NC}        ${BOLD}${TOTAL_RAM_GB} GB${NC} (Meets 8B model requirements, ~6.5GB total load)"
elif [ "$TOTAL_RAM_GB" -gt 0 ]; then
    echo -e "  ${YELLOW}!${NC} ${DIM}System RAM:${NC}        ${YELLOW}${TOTAL_RAM_GB} GB${NC} (Below 8GB; recommending compact 3B model)"
    TARGET_MODEL="llama3.2:3b"
else
    echo -e "  ${YELLOW}!${NC} ${DIM}System RAM:${NC}        Unable to detect RAM size. Proceeding with default 8B profile."
fi

# --- 1C. Available Disk Space ---
FREE_DISK_KB=$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')
FREE_DISK_GB=$((FREE_DISK_KB / 1024 / 1024))
if [ "$FREE_DISK_GB" -ge 8 ]; then
    echo -e "  ${GREEN}✓${NC} ${DIM}Free Disk Space:${NC}   ${BOLD}${FREE_DISK_GB} GB${NC} (Requires >= 8 GB for models and vector DB)"
elif [ "$FREE_DISK_GB" -gt 0 ]; then
    echo -e "  ${YELLOW}!${NC} ${DIM}Free Disk Space:${NC}   ${YELLOW}${FREE_DISK_GB} GB available${NC}. Low disk space warning (recommend >= 8 GB)."
fi

# --- 1D. Hardware Acceleration Detection ---
if [ "$OS_TYPE" = "Darwin" ] && [ "$ARCH_TYPE" = "arm64" ]; then
    echo -e "  ${GREEN}✓${NC} ${DIM}Acceleration:${NC}      ${BOLD}Apple Silicon Metal Unified GPU${NC} (Ultra-fast inference)"
elif command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || echo "NVIDIA GPU")
    echo -e "  ${GREEN}✓${NC} ${DIM}Acceleration:${NC}      ${BOLD}${GPU_NAME} (CUDA enabled)${NC}"
else
    echo -e "  ${DIM}• Acceleration:${NC}      Standard CPU SIMD/AVX Inference"
fi

# --- 1E. Core CLI Utilities Check ---
for util in curl tar gzip; do
    if ! command -v "$util" &>/dev/null; then
        echo -e "  ${RED}✗ Required utility '${util}' is missing. Please install it before proceeding.${NC}"
        exit 1
    fi
done
echo -e "  ${GREEN}✓${NC} ${DIM}System Utilities:${NC}  curl, tar, gzip available"

# ==============================================================================
# PHASE 2: PYTHON ENVIRONMENT CHECK
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[2/7] Checking Python runtime...${NC}"
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
        echo -e "  ${GREEN}✓${NC} Python ${PY_VER} detected (>= 3.9 requirement satisfied)."
    else
        echo -e "  ${RED}✗ Python ${PY_VER} detected. DNS-Expert requires Python 3.9 or higher.${NC}"
        exit 1
    fi
else
    echo -e "  ${RED}✗ Python 3 not found. Please install Python 3.9+ (https://www.python.org/downloads/).${NC}"
    exit 1
fi

# ==============================================================================
# PHASE 3: OLLAMA RUNTIME & DAEMON CHECK
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[3/7] Checking Ollama daemon...${NC}"
if ! command -v ollama &>/dev/null; then
    echo -e "  ${YELLOW}! Ollama not detected in PATH.${NC}"
    echo -e "    Installing Ollama via official script..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

if curl -s http://127.0.0.1:11434/api/tags &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Ollama daemon is actively running on localhost:11434."
else
    echo -e "  ${YELLOW}! Starting Ollama in background...${NC}"
    ollama serve >/dev/null 2>&1 &
    sleep 3
    if curl -s http://127.0.0.1:11434/api/tags &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Ollama daemon successfully started."
    else
        echo -e "  ${RED}✗ Failed to reach Ollama daemon on port 11434.${NC}"
        echo -e "    Please start it manually with 'ollama serve' in another terminal window."
        exit 1
    fi
fi

# ==============================================================================
# PHASE 4: VERIFY & PULL MODELS
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[4/7] Verifying and pulling required Ollama models...${NC}"
echo -e "  -> Checking nomic-embed-text (Embedding Model ~274MB)..."
ollama pull nomic-embed-text

if ! ollama list | grep -q "llama3.1:8b" && ! ollama list | grep -q "qwen2.5:7b" && ! ollama list | grep -q "dns-expert"; then
    echo -e "  -> Pulling base model ${TARGET_MODEL} (~4.7GB)..."
    ollama pull "${TARGET_MODEL}"
else
    echo -e "  ${GREEN}✓${NC} Base LLM already present in Ollama."
fi

# ==============================================================================
# PHASE 5: CREATE CUSTOM DNS-EXPERT MODEL
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[5/7] Configuring custom 'dns-expert' Modelfile in Ollama...${NC}"
if [ -f "Modelfile" ]; then
    ollama create dns-expert -f Modelfile
    echo -e "  ${GREEN}✓${NC} Custom DNS-Expert model created and registered."
else
    echo -e "  ${YELLOW}! Modelfile not found in current directory. Using default base model.${NC}"
fi

# ==============================================================================
# PHASE 6: SETUP PYTHON VENV & DEPENDENCIES
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[6/7] Setting up Python virtual environment and dependencies...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$SCRIPT_DIR"
echo -e "  ${GREEN}✓${NC} Dependencies installed."

# ==============================================================================
# PHASE 7: LINK CLI EXECUTABLE & DEPLOY ENCRYPTED KNOWLEDGE STORE
# ==============================================================================
echo -e "\n${CYAN}${BOLD}[7/7] Finalizing CLI executable and encrypted knowledge store...${NC}"
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.dns-expert"

# Auto-unpack encrypted binary container if present
if [ -f "$SCRIPT_DIR/dns_knowledge.dat" ]; then
    cp "$SCRIPT_DIR/dns_knowledge.dat" "$HOME/.dns-expert/dns_knowledge.dat"
    echo -e "  -> Unpacking encrypted knowledge container into secure local runtime cache..."
    "$VENV_DIR/bin/python" -c "
from pathlib import Path
from dns_expert.knowledge.crypto import decrypt_file
src = Path('$HOME/.dns-expert/dns_knowledge.dat')
dst = Path('$HOME/.dns-expert/dns_knowledge.db')
if src.exists() and (not dst.exists() or dst.stat().st_size == 0):
    decrypt_file(src, dst)
"
    echo -e "  ${GREEN}✓${NC} Knowledge vault unpacked successfully."
fi

cat << WRAPPER > "$HOME/.local/bin/dns-expert"
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" -m dns_expert.cli "\$@"
WRAPPER
chmod +x "$HOME/.local/bin/dns-expert"

echo -e "  ${GREEN}✓${NC} Executable linked to $HOME/.local/bin/dns-expert"

# ==============================================================================
# COMPLETION BANNER
# ==============================================================================
echo -e "\n${GREEN}${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}  DNS-Expert Installation & Pre-Flight Checks Passed! ${NC}"
echo -e "${GREEN}${BOLD}======================================================${NC}\n"
echo -e "Hardware profile verified: ${BOLD}${TOTAL_RAM_GB} GB RAM${NC}, ${BOLD}${FREE_DISK_GB} GB Free Disk${NC}."
echo -e "To start using DNS-Expert:"
echo -e "  1. Ensure ${BOLD}~/.local/bin${NC} is in your PATH (e.g. in ~/.zshrc or ~/.bashrc):"
echo -e "     ${YELLOW}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
echo -e "  2. Launch the interactive chat:"
echo -e "     ${BOLD}dns-expert${NC}"
echo -e "  3. Or run direct questions:"
echo -e "     ${BOLD}dns-expert ask \"How do I configure DNS cookies in BIND 9?\"${NC}"
echo -e "  4. Pipe diagnostic outputs directly:"
echo -e "     ${BOLD}dig +dnssec example.com | dns-expert debug${NC}\n"
