"""Random number streams (ADR-023).

Two kinds of stream, both derived from the config seed and fixed integers, never from Python's
salted `hash()`:
- entity streams, one generator per (stream, entity key), for creating population entities;
- day streams, one generator per (stream, day), drawing a vector over the stably ordered
  entity arrays in the daily loop (or per (stream, month) in the personal monthly loop).
"""

from __future__ import annotations

import zlib
from enum import IntEnum

import numpy as np


class Stream(IntEnum):
    # entity streams
    PERSONAL_SIGNUP = 1
    BUSINESS_SIGNUP = 2
    INTERNAL_SIGNUP = 3
    BRING_TO_WORK = 4
    DIRECT_SALES_SIGNUP = 5
    ENTERPRISE_CONTRACT = 6
    # day and month streams
    BUSINESS_ACTIVATE = 20
    SEATS = 21
    ACTIVITY = 22
    FEATURES = 23
    LIFECYCLE = 24
    PERSONAL_MONTH = 30
    # post-simulation streams over stably ordered arrays
    DEVICES = 40
    EMAILS = 41
    SYNC_LAG = 50


def entity_rng(seed: int, stream: Stream, *key: int) -> np.random.Generator:
    return np.random.default_rng([seed, int(stream), *key])


def period_rng(seed: int, stream: Stream, period: int) -> np.random.Generator:
    """One generator per (stream, day) or (stream, month)."""
    return np.random.default_rng([seed, int(stream), period])


def table_rng(seed: int, stream: Stream, table: str) -> np.random.Generator:
    """One generator per (stream, table), keyed by a stable checksum of the table name."""
    return np.random.default_rng([seed, int(stream), zlib.crc32(table.encode())])
