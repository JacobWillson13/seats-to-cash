"""In-memory simulation state: struct-of-arrays tables and append-only event logs."""

from __future__ import annotations

import numpy as np


class Columns:
    """A struct of numpy arrays that grows by doubling. Column views are `self.<name>`.

    Views are only valid until the next `append`, which may reallocate.
    """

    def __init__(self, spec: dict[str, tuple[type, object]], capacity: int = 1024):
        self._spec = spec
        self.n = 0
        self._data = {k: np.full(capacity, fill, dtype) for k, (dtype, fill) in spec.items()}

    def __getattr__(self, name: str) -> np.ndarray:
        data = self.__dict__.get("_data")
        if data is not None and name in data:
            return data[name][: self.n]
        raise AttributeError(name)

    def append(self, count: int) -> np.ndarray:
        need = self.n + count
        capacity = len(next(iter(self._data.values())))
        if need > capacity:
            new_capacity = max(need, 2 * capacity)
            for k, (dtype, fill) in self._spec.items():
                grown = np.full(new_capacity, fill, dtype)
                grown[: self.n] = self._data[k][: self.n]
                self._data[k] = grown
        idx = np.arange(self.n, need)
        self.n = need
        return idx


class Log:
    """Append-only event log; each `add` takes equal-length arrays or scalars."""

    def __init__(self, fields: dict[str, type]):
        self._fields = fields
        self._parts: dict[str, list[np.ndarray]] = {f: [] for f in fields}

    def add(self, **values) -> None:
        n = max((np.size(v) for v in values.values() if np.ndim(v) > 0), default=1)
        if n == 0:
            return
        if set(values) != set(self._fields):
            raise KeyError(f"log fields {sorted(self._fields)}, got {sorted(values)}")
        for f, dtype in self._fields.items():
            self._parts[f].append(np.broadcast_to(np.asarray(values[f], dtype), (n,)).copy())

    def arrays(self) -> dict[str, np.ndarray]:
        return {
            f: (np.concatenate(parts) if parts else np.zeros(0, self._fields[f]))
            for f, parts in self._parts.items()
        }


def ranks_within(groups: np.ndarray) -> np.ndarray:
    """0, 1, 2, ... within runs of equal values in an already sorted array."""
    if groups.size == 0:
        return np.zeros(0, np.int64)
    starts = np.r_[0, np.flatnonzero(groups[1:] != groups[:-1]) + 1]
    run_start = np.repeat(starts, np.diff(np.r_[starts, groups.size]))
    return np.arange(groups.size) - run_start
