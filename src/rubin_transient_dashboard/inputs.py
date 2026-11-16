"""Resolve a candidate without reading caller globals."""
import re

import numpy as np
import pandas as pd

CURVE_COLUMNS = ("midpointMjdTai", "band", "psfDiffFlux", "psfDiffFluxErr_corrected")


def _matching_rows(table, oid, label):
    if "diaObjectId" not in table:
        raise ValueError(f"{label} needs a diaObjectId column")
    ids = table["diaObjectId"]
    if pd.api.types.is_float_dtype(ids) or any(
        isinstance(value, (float, np.floating)) for value in ids.dropna()
    ):
        raise ValueError(f"{label} IDs must be integers or decimal strings, not floats")
    return table.loc[ids.eq(oid).fillna(False) | ids.eq(str(oid)).fillna(False)]


def resolve_target(object_id, object_table, *, lightcurves=None, catalog=None):
    """Return (integer ID, candidate row, measurements) for a selected candidate."""
    if not re.fullmatch(r"[0-9]+", str(object_id)):
        raise ValueError("Use a nonnegative integer or decimal string for object_id")
    oid = int(object_id)
    rows = _matching_rows(object_table, oid, "object_table")
    if len(rows) != 1:
        raise LookupError(f"Expected one row for {oid} in object_table; found {len(rows)}")
    # Preserve large integer IDs even when the other columns are floating point.
    obj = pd.Series({col: rows[col].iloc[0] for col in rows}, dtype=object)
    obj["diaObjectId"] = oid
    try:
        ra, dec = float(obj["ra"]), float(obj["dec"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("object_table must provide ra and dec in degrees") from exc
    if not (np.isfinite(ra) and np.isfinite(dec) and abs(dec) <= 90):
        raise ValueError("Object coordinates must be finite with declination in [-90, 90]")

    if lightcurves is not None:
        lc = _matching_rows(lightcurves, oid, "lightcurves")
    elif isinstance(obj.get("diaObjectForcedSource"), pd.DataFrame):
        lc = obj["diaObjectForcedSource"]
    elif catalog is not None:
        match = catalog.cone_search(ra=ra, dec=dec, radius_arcsec=2.0)
        match = match.query(f"diaObjectId == {oid}").to_dask_dataframe().head(1, npartitions=-1)
        if match.empty:
            raise LookupError(f"{oid} not found within 2 arcsec of its position in catalog")
        lc = match["diaObjectForcedSource"].iloc[0]
    else:
        raise ValueError("Supply lightcurves, a nested light curve, or catalog")
    if not isinstance(lc, pd.DataFrame) or lc.empty:
        raise ValueError(f"No light-curve measurements supplied for {oid}")
    missing = set(CURVE_COLUMNS).difference(lc.columns)
    if missing:
        raise ValueError(f"Missing light-curve columns: {sorted(missing)}")
    return oid, obj, lc
