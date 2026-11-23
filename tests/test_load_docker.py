#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""support load + every playbook recipe against a real throwaway ClickHouse (needs Docker).

    SUPPORT_TEST_DOCKER=1 python3 -m unittest tests/test_load_docker.py -v

Skipped unless SUPPORT_TEST_DOCKER=1. Uses its own state folder and removes the container.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from helpers import FIXTURE, ROOT, support

CLI = os.path.join(ROOT, "bin", "support")


@unittest.skipUnless(os.environ.get("SUPPORT_TEST_DOCKER") == "1", "set SUPPORT_TEST_DOCKER=1 (needs Docker)")
class LoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = tempfile.mkdtemp(prefix="support-state-")
        cls.env = {**os.environ, "SUPPORT_STATE_DIR": cls.state}
        p = cls.run_cli("load", FIXTURE)
        if p.returncode != 0:
            raise RuntimeError(p.stdout + p.stderr)
        cls.load_out = p.stdout

    @classmethod
    def tearDownClass(cls):
        cls.run_cli("down")
        shutil.rmtree(cls.state, ignore_errors=True)

    @classmethod
    def run_cli(cls, *args):
        return subprocess.run([sys.executable, "-I", CLI, *args], env=cls.env, capture_output=True, text=True,
                              timeout=900)

    def q(self, *args) -> str:
        p = self.run_cli("query", "--format", "TSV", *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_load_summary_and_password_file(self):
        self.assertIn("Loaded sample-bundle:", self.load_out)
        pw = os.path.join(self.state, "clickhouse.password")
        self.assertEqual(stat.S_IMODE(os.stat(pw).st_mode), 0o600)
        self.assertIn("127.0.0.1:", self.load_out)

    def test_every_recipe_runs(self):
        path = os.path.join(ROOT, "skills", "nano-support-investigate", "references", "queries.sql")
        with open(path, encoding="utf-8") as fh:
            names = list(support.parse_recipes(fh.read()))
        for name in names:
            with self.subTest(recipe=name):
                self.q("--recipe", name)

    def test_runbook_sql_runs(self):
        """Every ```sql block in the skills' markdown runs on a loaded bundle."""
        import glob
        import re
        for md in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "*.md")) +
                         glob.glob(os.path.join(ROOT, "skills", "*", "references", "*.md"))):
            with open(md, encoding="utf-8") as fh:
                blocks = re.findall(r"```sql\n(.*?)```", fh.read(), re.S)
            for i, block in enumerate(blocks):
                with self.subTest(file=os.path.basename(md), block=i):
                    self.q(block)

    def test_findings(self):
        self.assertIn("splunk_hec_ingst", self.q("--recipe", "vector-crash-loop"))
        self.assertIn("95-local-filter.toml", self.q("--recipe", "vector-config-files").splitlines()[0])
        self.assertIn("Restarting (78)", self.q("--recipe", "compose-status"))
        codes = self.q("--recipe", "ch-codes-in-logs")
        self.assertIn("241", codes)
        self.assertIn("252", codes)
        self.assertIn("grace_period", self.q("--recipe", "license"))
        self.assertIn("hunt sweep held", self.q("--recipe", "hunts-held"))
        self.assertIn("group allowed to sign in", self.q("--recipe", "auth-sso"))
        self.assertIn("API key was rejected", self.q("--recipe", "ai-provider"))
        self.assertIn("ocsf_logs_local", self.q("--recipe", "too-many-parts"))
        self.assertIn("nano-clickhouse", self.q("--recipe", "restarts-oom"))

    def test_reload_with_quote_and_backslash_in_name_replaces_rows(self):
        d = tempfile.mkdtemp()
        try:
            odd = os.path.join(d, "acme's\\bundle")
            shutil.copytree(FIXTURE, odd)
            for _ in range(2):
                p = self.run_cli("load", odd)
                self.assertEqual(p.returncode, 0, p.stderr)
            n = self.q("SELECT count() FROM facts WHERE bundle = 'acme\\'s\\\\bundle'").strip()
            base = self.q("SELECT count() FROM facts WHERE bundle = 'sample-bundle'").strip()
            self.assertEqual(n, base)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_query_is_read_only(self):
        p = self.run_cli("query", "INSERT INTO facts (key, value) VALUES ('x', 'y')")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("readonly", p.stderr.lower())

    def test_bound_to_loopback(self):
        p = subprocess.run(["docker", "ps", "--filter", "label=nano-support=1", "--format", "{{.Ports}}"],
                           capture_output=True, text=True)
        self.assertIn("127.0.0.1:", p.stdout)
        self.assertNotIn("0.0.0.0", p.stdout)


if __name__ == "__main__":
    unittest.main()
