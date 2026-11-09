"""The OpenDMTQ PC client: a launcher (portal) that connects to an OpenDMTQ server, signs in, keeps that server's app,
sets the picture and the sound up for a PC, and starts the game in the player for Windows; and its installer.

The version is the project's one version (deploy/helm/opendmtq/Chart.yaml): a build writes it into version.txt beside
this file (client/packaging/windows/build.sh); run from a checkout, it is read from the chart itself.
"""

import os
import re

# This package's folder: version.txt lives here in a build.
_HERE = os.path.dirname(os.path.abspath(__file__))


def _version():
    """The version a build wrote, else the chart's in a checkout, else 0.0.0 (a copy without either)."""
    try:
        with open(os.path.join(_HERE, "version.txt"), encoding="utf-8") as f:
            written = f.read().strip()
        # An empty file is no version: the chart's takes its place.
        if written:
            return written
    except OSError:
        # No build wrote one: run from the repository.
        pass
    chart = os.path.join(_HERE, "..", "..", "deploy", "helm", "opendmtq", "Chart.yaml")
    try:
        with open(chart, encoding="utf-8") as f:
            # The chart's own "version: 1.2.3" line, as the release checks read it.
            found = re.search(r"^version:\s*\"?([0-9A-Za-z.+-]+)\"?\s*$", f.read(), re.M)
        if found:
            return found.group(1)
    except OSError:
        # Neither: a copy of the package on its own.
        pass
    return "0.0.0"


__version__ = _version()
