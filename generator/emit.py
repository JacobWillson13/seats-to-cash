"""Parquet writer: fixed schema, stable sort, fixed writer settings, so equal inputs give
byte-identical files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from generator.tables import Table

WRITE_OPTIONS = {
    "compression": "zstd",
    "compression_level": 3,
    "row_group_size": 1 << 20,
    "use_dictionary": True,
    "write_statistics": True,
    "version": "2.6",
}


def to_arrow(table: Table, columns: dict[str, object]) -> pa.Table:
    """Build an Arrow table. Values are arrays or lists; masked arrays carry nulls.

    Timestamps are int64 microseconds since the epoch; dates are int days since the epoch.
    """
    if set(columns) != {c.name for c in table.columns}:
        missing = {c.name for c in table.columns} - set(columns)
        extra = set(columns) - {c.name for c in table.columns}
        raise ValueError(f"{table.name}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    arrays = []
    for col in table.columns:
        values = columns[col.name]
        mask = None
        if isinstance(values, np.ma.MaskedArray):
            mask = np.ma.getmaskarray(values)
            values = values.data
        if isinstance(values, np.ndarray) and pa.types.is_temporal(col.type):
            storage = pa.int64() if pa.types.is_timestamp(col.type) else pa.int32()
            arrays.append(pa.array(values.astype(storage.to_pandas_dtype()), storage, mask=mask)
                          .cast(col.type))  # fmt: skip
        else:
            arrays.append(pa.array(values, col.type, mask=mask))
        if not col.nullable and arrays[-1].null_count:
            raise ValueError(f"{table.name}.{col.name} has {arrays[-1].null_count} nulls")
    return pa.Table.from_arrays(arrays, schema=table.schema)


def write(table: Table, columns: dict[str, object], root: Path) -> int:
    data = to_arrow(table, columns)
    data = data.take(pc.sort_indices(data, [(k, "ascending") for k in table.sort_key]))
    keys = data.select(list(table.primary_key)).group_by(list(table.primary_key)).aggregate([])
    if keys.num_rows != data.num_rows:
        raise ValueError(f"{table.name}: primary key {table.primary_key} is not unique")
    path = root / table.source / f"{table.name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(data, path, **WRITE_OPTIONS)
    return data.num_rows
