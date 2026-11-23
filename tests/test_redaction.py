#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Redaction of live probes (through nano's own Redactor) and what probes may read.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import os
import re
import tarfile
import tempfile
import unittest

from helpers import nano_tool, support

CH_PASSWORD = "chAdm1n-S3cret-Value-77"
LICENSE = "Zk3q9V_r8XyT2mN4pL6sA1bC5dE7fG9hJ0kQwErTyUi"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfMDEiLCJleHAiOjE5MDAwMDAwMDB9"
       ".c2lnbmF0dXJlLXZhbHVlLWhlcmUtMTIzNDU2Nzg5MA")
PEM = ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n"
       "-----END PRIVATE KEY-----")


class FakeProber:
    """Just enough of Prober for keep(): the method under test is the real one."""
    keep = support.Prober.keep

    def __init__(self, redact):
        self.redact = redact
        self.out = {}


class ProbeRedactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = nano_tool()

    def prober(self):
        red = self.sb.Redactor()
        red.add_env({"CLICKHOUSE_ADMIN_PASSWORD": CH_PASSWORD, "LICENSE_TOKEN": LICENSE,
                     "NANO_LICENSE_MODE": "online"})
        return FakeProber(red)

    def test_env_secret_values_replaced_in_rows(self):
        p = self.prober()
        p.keep("ch-errors", True, rows=[{"name": "AUTHENTICATION_FAILED", "code": 516,
                                         "last_error_message": f"wrong password {CH_PASSWORD} for user"}])
        dumped = json.dumps(p.out)
        self.assertNotIn(CH_PASSWORD, dumped)
        self.assertIn("[REDACTED", dumped)
        self.assertEqual(p.out["ch-errors"]["rows"][0]["code"], 516)  # structure survives

    def test_token_shapes_replaced_in_text_and_errors(self):
        p = self.prober()
        p.keep("vector-topology", False, text=f"Authorization: Bearer abcDEF0123456789.tok {JWT}",
               error=f"postgres://nanosiem:pgPa55-w0rd-Value-88@postgres:5432/nanosiem {PEM}")
        dumped = json.dumps(p.out)
        for secret in ("abcDEF0123456789", JWT[:30], "pgPa55-w0rd-Value-88", "MIIEvQIBADAN"):
            self.assertNotIn(secret, dumped)

    def test_license_token_anywhere(self):
        p = self.prober()
        p.keep("health", True, rows=[{"detail": f"check-in sent {LICENSE}"}])
        self.assertNotIn(LICENSE, json.dumps(p.out))

    def test_non_secrets_survive(self):
        p = self.prober()
        p.keep("pg-licensing-state", True, rows=[{"state": "grace_period", "valid": True}])
        self.assertEqual(p.out["pg-licensing-state"]["rows"][0]["state"], "grace_period")

    def test_second_pass_finds_planted_secret(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.tar.gz")
            inner = io.BytesIO()
            with tarfile.open(fileobj=inner, mode="w:gz") as t:
                data = b"ok line\npassword=hunter2hunter2\n"
                info = tarfile.TarInfo("nano-support-x/hosts/h/logs/nano-api.log")
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            support.wrap_archive(path, {"bundle/nano-support-x.tar.gz": inner.getvalue(),
                                        "probes/probes.json": b'{"probes": {"x": {"ok": true}}}'})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            found = support.secret_findings(path, self.sb)
            self.assertEqual(found, [("bundle: hosts/h/logs/nano-api.log", 2)])

    def test_already_redacted_text_is_not_a_finding(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "y.tar.gz")
            support.wrap_archive(path, {"env.txt": b"CLICKHOUSE_ADMIN_PASSWORD=[REDACTED]\nNANO_VERSION=2.0.34\n",
                                        "probes/probes.json": b'{"pg-licensing-state": {"ok": true}}'})
            self.assertEqual(support.secret_findings(path, self.sb), [])


class ProbeScopeTests(unittest.TestCase):
    """Probes never read query text or table data."""

    def test_clickhouse_probes_read_no_query_text(self):
        for name, sql in support.ch_probe_queries(3600):
            low = sql.lower()
            # Columns that hold query text in system.query_log / processes.
            self.assertIsNone(re.search(r"\b(query|formatted_query|query_text)\b(?!_)", low.replace("system.query_log", "")),
                              f"{name} reads query text: {sql}")
            self.assertNotIn("nanosiem.", low, f"{name} reads a nano table")
            self.assertTrue(low.lstrip().startswith("select"), name)

    def test_postgres_probes_read_no_query_text(self):
        for name, sql in support.PG_PROBE_QUERIES:
            low = sql.lower()
            self.assertNotRegex(low, r"\bquery\b", name)
            self.assertNotIn("raw_response", low, name)
            self.assertTrue(low.startswith("select"), name)

    def test_vector_probes_never_tap(self):
        self.assertNotIn("tap", support.VECTOR_TOPOLOGY_GQL.lower())


if __name__ == "__main__":
    unittest.main()
