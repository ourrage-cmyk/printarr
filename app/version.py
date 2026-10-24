"""Which build is running: the package version, and the git commit baked into the image at build time.

The Dockerfile sets PRINTARR_BUILD_SHA from the VERSION build argument. CI passes the commit sha;
a plain local build says "dev".
"""

from __future__ import annotations

import os

PACKAGE_VERSION = "0.2.0"
UNKNOWN_SHA = "dev"


def build_info() -> dict[str, str]:
    sha = os.environ.get("PRINTARR_BUILD_SHA", "").strip() or UNKNOWN_SHA
    return {"version": PACKAGE_VERSION, "git_sha": sha}
