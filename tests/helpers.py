# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared test helpers: load bin/support and nano's bundle tool as modules."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sample-bundle")
sys.path.insert(0, os.path.join(ROOT, "tests"))

import fetch_nano_tool  # noqa: E402


def load(path: str, name: str):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


support = load(os.path.join(ROOT, "bin", "support"), "support_cli")


def nano_tool_path() -> str:
    return fetch_nano_tool.path()


def nano_tool():
    return support.load_bundle_module(nano_tool_path())
