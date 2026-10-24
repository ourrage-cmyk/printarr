"""Which build is running: its version and the git commit it was built from.

The Dockerfile sets PRINTARR_BUILD_VERSION and PRINTARR_BUILD_SHA from build arguments. CI sets the
version from the workflow run number (0.2.<run>) and the sha from the commit, so nobody edits a
number by hand. A plain local build says PACKAGE_VERSION and "dev".
"""

from __future__ import annotations

import os

PACKAGE_VERSION = "0.2.0"
UNKNOWN_SHA = "dev"


def build_info() -> dict[str, str]:
    version = os.environ.get("PRINTARR_BUILD_VERSION", "").strip() or PACKAGE_VERSION
    sha = os.environ.get("PRINTARR_BUILD_SHA", "").strip() or UNKNOWN_SHA
    return {"version": version, "git_sha": sha}
