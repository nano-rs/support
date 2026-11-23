#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download nano's support bundle tool for the tests, pinned by version AND sha256.

    python3 tests/fetch_nano_tool.py        # writes .cache/nano-support-bundle-<version>

The tests use nano's own redaction (support never ships a copy of it), so they need the
real file. Bump both values together after checking the new file.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

VERSION = "2.0.34"
SHA256 = "0a8912c4814bc81061908c9d8296c9f45990b550ba9c7c9a17dbc1e3708eeb61"
URL = f"https://raw.githubusercontent.com/nano-rs/nano/v{VERSION}/scripts/nano-support-bundle"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, ".cache", f"nano-support-bundle-{VERSION}")


def path() -> str:
    """The tool's path: SUPPORT_BUNDLE_TOOL, else the cached download (fetched if missing)."""
    env = os.environ.get("SUPPORT_BUNDLE_TOOL")
    if env:
        return env
    if not os.path.isfile(DEST):
        fetch()
    return DEST


def fetch() -> str:
    with urllib.request.urlopen(URL, timeout=60) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        sys.exit(f"{URL}: sha256 {digest} does not match the pinned {SHA256}")
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with open(DEST, "wb") as fh:
        fh.write(data)
    return DEST


if __name__ == "__main__":
    print(fetch())
