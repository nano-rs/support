#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-repository hygiene: no private addresses, internal names, tokens, em dashes or UK spelling.

Fixture data must use the documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and
example.com. Loopback, 0.0.0.0, and Docker's default bridge range in sample output are allowed.
"""
from __future__ import annotations

import os
import re
import unittest

from helpers import ROOT

SKIP_DIRS = {".git", ".cache", "__pycache__", ".ruff_cache"}
SKIP_FILES = {"LICENSE"}

# Built from parts so this file does not match itself.
PATTERNS = {
    "carrier-grade NAT or tailnet address": re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "private 192.168 address": re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    "private 10.x address": re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "internal repository name": re.compile("nano" + r"-main\b|nano" + r"siem-worktrees|docs" + "-internal"),
    "issue tracker reference": re.compile(r"\b" + "NAN" + r"-\d+|\b" + "Lin" + r"ear\b|lin" + r"ear\.app"),
    "lab host": re.compile("prox" + "mox|herd" + "r|tail" + r"scale|\bpluto\b|\bsaturn\b", re.I),
    "token shape": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9]{20,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
                              r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bnit_[A-Za-z0-9_-]{8,}|\bnal_[A-Za-z0-9]{8,}"),
    "em dash": re.compile(chr(0x2014)),
    "UK spelling": re.compile(r"\blicen[c]e\b|\bcancell(ed|ing)\b|\bbehaviour\b|\bcolour\b|\borganis(e|ation)\b|\bcatalogue\b", re.I),
}

# Test inputs that deliberately hold secret-shaped strings (they test that redaction removes them).
ALLOWED = {
    ("tests/test_redaction.py", "token shape"),
    ("tests/test_cli.py", "token shape"),
    ("tests/test_hygiene.py", "token shape"),
}


def files():
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if n in SKIP_FILES or n.endswith((".pyc", ".tar.gz")):
                continue
            path = os.path.join(root, n)
            yield os.path.relpath(path, ROOT), path


class HygieneTests(unittest.TestCase):
    def test_no_internal_or_secret_text(self):
        problems = []
        for rel, path in files():
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except UnicodeDecodeError:
                continue
            for label, rx in PATTERNS.items():
                if (rel, label) in ALLOWED:
                    continue
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    problems.append(f"{rel}:{line}: {label}: {m.group(0)!r}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_fixture_addresses_are_documentation_ranges(self):
        allowed = re.compile(r"^(192\.0\.2|198\.51\.100|203\.0\.113)\.|^127\.|^0\.0\.0\.0$")
        version = re.compile(r"^2[5-9]\.\d+\.\d+\.\d+$")  # ClickHouse versions look like addresses
        bad = []
        for rel, path in files():
            if not rel.startswith("tests/fixtures/"):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", fh.read()):
                    if not allowed.match(ip) and not version.match(ip):
                        bad.append(f"{rel}: {ip}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
