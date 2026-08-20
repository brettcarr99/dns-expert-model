"""Cryptographic Container & Obfuscation Engine for DNS Knowledge Store."""

import hashlib
import hmac
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Optional

# Embedded internal key derivation seed
_INTERNAL_SEED = b"dns-expert-knowledge-vault-v1-auth-protocol-rfc-vendor-corpus"
_MAGIC_HEADER = b"DNSX"


def _derive_key(salt: bytes, custom_seed: Optional[bytes] = None) -> bytes:
    """Derive a 256-bit encryption key using PBKDF2 HMAC-SHA256."""
    seed = custom_seed or _INTERNAL_SEED
    return hashlib.pbkdf2_hmac("sha256", seed, salt, iterations=10000, dklen=32)


def encrypt_file(
    input_file: Path,
    output_file: Path,
    custom_seed: Optional[bytes] = None,
) -> int:
    """Compress and encrypt a database file into a secure binary blob."""
    input_path = Path(input_file)
    output_path = Path(output_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # 1. Read & Compress payload
    raw_data = input_path.read_bytes()
    compressed = zlib.compress(raw_data, level=9)

    # 2. Generate random salt and nonce
    salt = os.urandom(16)
    nonce = os.urandom(16)
    key = _derive_key(salt, custom_seed)

    # 3. Stream encrypt using keystream XOR (AES/HMAC-CTR)
    ciphertext = _apply_keystream(compressed, key, nonce)

    # 4. Generate authentication MAC
    auth_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()

    # 5. Pack binary container
    # Header: Magic (4B) | Salt (16B) | Nonce (16B) | Tag (32B) | Ciphertext
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(_MAGIC_HEADER)
        f.write(salt)
        f.write(nonce)
        f.write(auth_tag)
        f.write(ciphertext)

    return output_path.stat().st_size


def decrypt_file(
    input_file: Path,
    output_file: Path,
    custom_seed: Optional[bytes] = None,
) -> int:
    """Verify and decrypt an encrypted binary blob back into SQLite database."""
    input_path = Path(input_file)
    output_path = Path(output_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Encrypted container not found: {input_path}")

    with open(input_path, "rb") as f:
        magic = f.read(4)
        if magic != _MAGIC_HEADER:
            raise ValueError(f"Invalid container format (expected magic {_MAGIC_HEADER!r}, got {magic!r})")

        salt = f.read(16)
        nonce = f.read(16)
        expected_tag = f.read(32)
        ciphertext = f.read()

    # 1. Derive key
    key = _derive_key(salt, custom_seed)

    # 2. Verify MAC
    calculated_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_tag, calculated_tag):
        raise ValueError("Cryptographic verification failed: corrupted or altered container.")

    # 3. Decrypt ciphertext
    compressed = _apply_keystream(ciphertext, key, nonce)

    # 4. Decompress payload
    raw_data = zlib.decompress(compressed)

    # 5. Write restored database
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw_data)

    return output_path.stat().st_size


def _apply_keystream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    """Fast CTR-mode keystream generator using HMAC-SHA256 blocks."""
    out = bytearray(len(data))
    block_idx = 0
    data_len = len(data)
    offset = 0

    while offset < data_len:
        counter = struct.pack(">Q", block_idx)
        block_key = hmac.new(key, nonce + counter, hashlib.sha256).digest()
        chunk_len = min(32, data_len - offset)
        for i in range(chunk_len):
            out[offset + i] = data[offset + i] ^ block_key[i]
        offset += chunk_len
        block_idx += 1

    return bytes(out)
