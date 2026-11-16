import unittest
from unittest.mock import Mock, patch

import matplotlib.pyplot as plt
import pandas as pd
from astropy.table import QTable
from astropy.utils import iers

from rubin_transient_dashboard import inspect_transient, resolve_target


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.oid = 753900763427635843
        self.objects = pd.DataFrame({"diaObjectId": [self.oid], "ra": [53.13], "dec": [-28.1]})
        self.curve = pd.DataFrame({
            "diaObjectId": list(map(str, [self.oid, self.oid, self.oid + 1])),
            "midpointMjdTai": [61000., 61002., 61003.],
            "band": ["r", "g", "i"],
            "psfDiffFlux": [-25., 4., 900.],
            "psfDiffFluxErr_corrected": [1., 1., 1.],
        })
        self.addCleanup(plt.close, "all")
        iers_config = iers.conf.set_temp("auto_download", False)
        iers_config.__enter__()
        self.addCleanup(iers_config.__exit__, None, None, None)

    def test_offline_plot_uses_only_selected_object(self):
        with patch("rubin_transient_dashboard.dashboard.display") as display:
            result = inspect_transient(str(self.oid), object_table=self.objects, lightcurves=self.curve)
        display.assert_not_called()
        self.assertEqual(result["object"]["diaObjectId"], self.oid)
        self.assertEqual(result["light_curve_peak"]["flux"], -25.)
        self.assertEqual(len(result["light_curve_figure"].axes), 2)
        self.assertEqual(result["errors"], {})

    def test_nested_and_catalog_inputs(self):
        nested = self.objects.copy()
        nested["diaObjectForcedSource"] = [self.curve.iloc[:2]]
        self.assertEqual(len(resolve_target(self.oid, nested)[2]), 2)
        catalog = Mock()
        catalog.cone_search.return_value.query.return_value.to_dask_dataframe.return_value.head.return_value = nested
        self.assertEqual(len(resolve_target(self.oid, self.objects, catalog=catalog)[2]), 2)
        catalog.cone_search.assert_called_once_with(ra=53.13, dec=-28.1, radius_arcsec=2.)

    def test_rejects_rounded_ids(self):
        with self.assertRaisesRegex(ValueError, "not floats"):
            resolve_target(self.oid, self.objects.astype({"diaObjectId": float}), lightcurves=self.curve)

    def test_skybot_epoch_and_observer(self):
        with patch("rubin_transient_dashboard.dashboard.query_skybot_neighbors", return_value=QTable()) as query:
            result = inspect_transient(self.oid, object_table=self.objects, lightcurves=self.curve, panels=("skybot",))
        self.assertEqual(query.call_args.kwargs["location"], "X05")
        epoch = query.call_args.args[1]
        self.assertEqual(epoch.scale, "utc")
        self.assertAlmostEqual(epoch.tai.mjd, 61000)
        self.assertEqual(result["skybot_status"], "queried")


if __name__ == "__main__":
    unittest.main()
