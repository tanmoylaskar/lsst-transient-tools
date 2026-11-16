# First GitHub release

## Licensing

The [interim license](../LICENSE) permits use of unchanged copies for
noncommercial purposes. Changes, redistribution, and commercial use require
separate written permission. There is no institutional exception.

Before changing the license, confirm rights and contributor attribution.
Do not apply the project's license to third-party packages, survey images,
or catalog results.

## Release checklist

1. If the license changes, update `LICENSE`, the README, and the package
   metadata together before building new artifacts.
2. Run the synthetic example and tests. In a Rubin notebook, run one full
   inspection to check LSDB, Butler, Legacy, NED, SIMBAD, SkyBoT and TNS. Record
   unavailable services separately from empty matches. Never commit credentials
   or private candidate tables.
3. Build and install the artifact from a clean checkout:
   `python -m pip install build`, `python -m build`, then
   `python -m pip install dist/*.whl`. Run the offline example against it.
4. Push changes to the GitHub repository and wait for CI to pass. Tag the
   release as `v0.1.0` (or the version in `pyproject.toml`) and attach rebuilt
   distribution files if desired. Publishing on PyPI is optional.
