"""Deterministic vendor-style IDs: prefix + base62 of a keyed hash of (seed, namespace, key)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def make_id(seed: int, namespace: str, key: object, prefix: str, length: int = 14) -> str:
    digest = hashlib.blake2b(f"{seed}:{namespace}:{key}".encode(), digest_size=16).digest()
    n = int.from_bytes(digest, "big")
    chars = []
    for _ in range(length):
        n, r = divmod(n, 62)
        chars.append(ALPHABET[r])
    return prefix + "".join(chars)


def make_ids(
    seed: int, namespace: str, keys: Iterable[object], prefix: str, length: int = 14
) -> list[str]:
    ids = [make_id(seed, namespace, k, prefix, length) for k in keys]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"ID collision in namespace {namespace!r}; lengthen the IDs")
    return ids


def machine_key_hash(seed: int, machine: int) -> str:
    """Stable per physical machine across tailnets (SPEC 4.4)."""
    return hashlib.blake2b(f"{seed}:machine:{machine}".encode(), digest_size=32).hexdigest()
