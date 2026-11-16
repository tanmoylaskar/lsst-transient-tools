# First GitHub release

## License decision

This checkout is a release draft. The maintainers have not yet granted a public
reuse license. Do not publish the draft as a licensed release until the license
and copyright holder(s) are confirmed.

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
is the proposed software license. It allows permitted research use, changes, and
redistribution subject to its terms. It expressly permits use by specified
institutions, including universities and public research organizations,
regardless of funding. It preserves license and required notices, but does not
impose a ShareAlike obligation on downstream modifications. If either the
institutional permission or the absence of ShareAlike conflicts with the
project's intent, resolve that before release.

[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) is an option
for original documentation or figures if separately designated.
[Creative Commons recommends against using its licenses for software](https://creativecommons.org/faq/#can-i-apply-a-creative-commons-license-to-software).
Do not apply the project's license to third-party packages, survey images, or
catalog results. Confirm that all contributors can grant the chosen terms.

## Release checklist

1. Add the approved license text to `LICENSE`, record required copyright notices,
   and add the license to package metadata. Update the README to identify the
   license and its scope.
2. Run the synthetic example and tests. In a Rubin notebook, run one full
   inspection to check LSDB, Butler, Legacy, NED, SIMBAD, SkyBoT and TNS. Record
   unavailable services separately from empty matches. Never commit credentials
   or private candidate tables.
3. Build and install the artifact from a clean checkout:
   `python -m pip install build`, `python -m build`, then
   `python -m pip install dist/*.whl`. Run the offline example against it.
4. Create the repository in the chosen GitHub account or organization, push
   this directory as the repository root, and wait for CI to pass. Tag the
   release as `v0.1.0` (or the version in `pyproject.toml`) and attach rebuilt
   distribution files if desired. Publishing on PyPI is optional.
