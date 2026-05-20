from __future__ import annotations

import hashlib
import re
from collections import Counter


TOKEN_RE = re.compile(r"[\w']+", flags=re.UNICODE)


def compute_simhash(text: str, bits: int = 64) -> int:
    if bits <= 0:
        raise ValueError("bits must be positive")

    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0

    weights = Counter(tokens)
    vector = [0] * bits

    for token, weight in weights.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        token_hash = int.from_bytes(digest, byteorder="big")
        for bit_idx in range(bits):
            bit_set = (token_hash >> bit_idx) & 1
            vector[bit_idx] += weight if bit_set else -weight

    result = 0
    for bit_idx, score in enumerate(vector):
        if score >= 0:
            result |= 1 << bit_idx
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def simhash_to_hex(value: int, bits: int) -> str:
    width = bits // 4
    return f"0x{value:0{width}x}"


def parse_simhash(simhash_value: str) -> int:
    if simhash_value.startswith("0x"):
        return int(simhash_value, 16)
    return int(simhash_value)
