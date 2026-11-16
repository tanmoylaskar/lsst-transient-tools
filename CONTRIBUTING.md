# Contributing

Bug reports and feature suggestions are welcome. Contact the maintainer for
written permission before modifying or redistributing the code under the
[interim license](LICENSE).
For a bug report, include Python and package versions, the failing panel, and
a minimal example with synthetic or public data. Remove credentials and
private coordinates from shared logs.

Use a virtual environment, install with `python -m pip install -e .`, then run:

```sh
MPLBACKEND=Agg python -m unittest discover -s tests -v
python examples/offline_demo.py /tmp/rubin-demo.png
```

Tests should not depend on live archives. Mock lookup responses for new panel
behavior and describe any live Rubin checks separately. Preserving exact
integer identifiers and distinguishing no matches from service failures are
both part of the interface.
