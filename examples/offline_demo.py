"""Generate a dashboard example from synthetic photometry, with no archives."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from rubin_transient_dashboard import resolve_target, plot_inspection_light_curves


def sample_tables():
    """Return synthetic candidate and photometry DataFrames."""
    object_id = 100000000000000001
    candidates = pd.DataFrame({"diaObjectId": [object_id], "ra": [53.0], "dec": [-28.0]})
    # Use staggered visits and different amplitudes so the bands separate in the zoom.
    points = []
    for band, scale, offset in [("g", 0.65, 0.04), ("r", 0.85, 0.0), ("i", 1.0, 0.02)]:
        for day, flux in [
            (-7, 15), (-3, -30), (-0.21, 780), (-0.11, 890), (-0.02, 950),
            (0.08, 870), (0.22, 760), (2, 375), (5, 105), (9, -25),
        ]:
            points.append((object_id, 61000 + day + offset, band, scale * flux, 35))
    photometry = pd.DataFrame(points, columns=[
        "diaObjectId", "midpointMjdTai", "band", "psfDiffFlux", "psfDiffFluxErr_corrected",
    ])
    return candidates, photometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("demo-lightcurve.png"))
    args = parser.parse_args()
    candidates, photometry = sample_tables()
    oid = candidates["diaObjectId"].iloc[0]
    _, _, lc = resolve_target(oid, candidates, lightcurves=photometry)
    fig, _ = plot_inspection_light_curves(lc, oid, show=False)
    fig.savefig(args.output, dpi=110)
    plt.close(fig)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
