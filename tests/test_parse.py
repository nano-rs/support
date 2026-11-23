#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bundle parsing: log line formats, tables, and the synthetic sample bundle (no Docker)."""
from __future__ import annotations

import datetime as dt
import os
import tarfile
import tempfile
import unittest

from helpers import FIXTURE, support

P = support.parse_log_line


class LogLineTests(unittest.TestCase):
    def test_tracing_plain_with_ansi_and_docker_prefix(self):
        line = ("2026-11-23T13:16:51.505039287Z \x1b[2m2026-11-23T13:16:51.504965Z\x1b[0m \x1b[32m INFO\x1b[0m "
                "\x1b[1mservice\x1b[0m\x1b[1m{\x1b[0m\x1b[3mservice.name\x1b[0m\x1b[2m=\x1b[0m\"nanosiem-api\" "
                "\x1b[3mversion\x1b[0m\x1b[2m=\x1b[0m\"2.0.34\"\x1b[1m}\x1b[0m\x1b[2m:\x1b[0m \x1b[2mnanosiem_api\x1b[0m"
                "\x1b[2m:\x1b[0m Starting NanoSIEM API server")
        r = P(line)
        self.assertEqual((r["level"], r["target"], r["message"]), ("INFO", "nanosiem_api", "Starting NanoSIEM API server"))
        self.assertEqual(r["ts"], "2026-11-23 13:16:51.505039")

    def test_tracing_json(self):
        r = P('2026-11-23T10:00:00.5Z {"timestamp":"2026-11-23T10:00:00.123456Z","level":"ERROR","fields":'
              '{"message":"Refusing to start: PostgreSQL schema is behind","error":"x"},"target":"nanosiem_search",'
              '"span":{"name":"service"}}')
        self.assertEqual(r["level"], "ERROR")
        self.assertEqual(r["message"], "Refusing to start: PostgreSQL schema is behind")
        self.assertEqual(r["fields"]["error"], "x")
        self.assertIn("span", r["fields"])
        self.assertEqual(r["ts"], "2026-11-23 10:00:00.123456")

    def test_vector(self):
        r = P("2026-11-23T13:20:52.215782Z 2026-11-23T13:20:52.215761Z ERROR vector::cli: Configuration error. "
              "error=Input \"x\" for transform \"y\" doesn't match any components.")
        self.assertEqual((r["level"], r["target"]), ("ERROR", "vector::cli"))
        self.assertTrue(r["message"].startswith("Configuration error."))
        r = P("2026-11-23T13:16:54.774Z 2026-11-23T13:16:54.774250Z  WARN source{[REDACTED:payload]}: "
              "vector::config::source: Enabling `acknowledgements` ...")
        self.assertEqual((r["level"], r["target"]), ("WARN", "vector::config::source"))

    def test_vector_internal_logs_json(self):
        r = P('2026-11-23T13:17:01.13Z {"host":"h","message":"Configuration warnings.","metadata":{[REDACTED:payload]},'
              '"pid":1,"source_type":"internal_logs","timestamp":"2026-11-23T13:16:54.772709226Z"}')
        # nano's payload scrub breaks the JSON: the line still parses as text, never raises
        self.assertIn("Configuration warnings.", r["message"])
        r = P('{"message":"Events dropped","metadata":{"level":"ERROR","target":"vector::sinks"},'
              '"source_type":"internal_logs","timestamp":"2026-11-23T13:16:54.772709226Z"}')
        self.assertEqual((r["level"], r["target"], r["message"]), ("ERROR", "vector::sinks", "Events dropped"))

    def test_vrl_diagnostic_and_entrypoint(self):
        self.assertEqual(P("2026-11-23T13:16:54Z warning[E620]: can't abort infallible function")["level"], "WARN")
        self.assertEqual(P("2026-11-23T13:16:54Z error[E110]: invalid argument")["level"], "ERROR")

    def test_clickhouse(self):
        r = P("2026-11-23T13:30:55.1Z 2026.11.23 13:30:55.120300 [ 812 ] {a1b2} <Error> executeQuery: Code: 241. "
              "DB::Exception: memory limit exceeded")
        self.assertEqual((r["level"], r["target"], r["fields"]["code"]), ("ERROR", "executeQuery", 241))
        self.assertEqual(P("2026.11.23 13:30:58.0 [ 1 ] {} <Fatal> Application: Child process was terminated")["level"],
                         "FATAL")
        self.assertEqual(P("2026.11.23 13:30:58.0 [ 1 ] {} <Information> Application: Ready")["level"], "INFO")

    def test_postgres(self):
        r = P("2026-11-23T13:13:25Z 2026-11-23 13:13:25.191 UTC [64] ERROR:  relation \"x\" does not exist")
        self.assertEqual(r["level"], "ERROR")
        self.assertEqual(r["message"], 'relation "x" does not exist')

    def test_nginx_and_valkey(self):
        r = P('2026-11-23T13:00:00Z 198.51.100.7 - - [23/Nov/2026:13:00:00 +0000] "POST /api/auth/login HTTP/1.1" 429 54 "-" "x"')
        self.assertEqual((r["level"], r["target"], r["fields"]["status"]), ("WARN", "access", 429))
        r = P("2026-11-23T13:13:18Z 7:M 23 Nov 2026 13:13:18.899 # WARNING Memory overcommit must be enabled!")
        self.assertEqual(r["level"], "WARN")

    def test_timestamp_offsets(self):
        self.assertEqual(support.to_iso("2026-11-23T08:00:00-05:00"), "2026-11-23 13:00:00.000000")
        self.assertEqual(support.to_iso("2026.11.23 13:00:00.1"), "2026-11-23 13:00:00.100000")
        self.assertIsNone(support.to_iso("yesterday"))

    def test_never_raises(self):
        for junk in ("", "{", "{not json}", "\x00\x01", "Code: x", "## heading"):
            P(junk)


class TableTests(unittest.TestCase):
    def test_fixed_table_compose_ps(self):
        text = ("NAME          IMAGE                              SERVICE   STATUS\n"
                "nano-vector   ghcr.io/nano-rs/vector:0.61.0      vector    Restarting (78) 9 seconds ago\n"
                "nano-api      ghcr.io/nano-rs/nano-api:2.0.34    nano-api  Up 2 days (healthy)\n")
        rows = support.parse_fixed_table(text)
        self.assertEqual(rows[0]["STATUS"], "Restarting (78) 9 seconds ago")
        self.assertEqual(rows[1]["SERVICE"], "nano-api")
        self.assertIsNone(support.parse_fixed_table("just text\nmore text"))

    def test_k8s_events_ages(self):
        text = ("LAST SEEN   TYPE      REASON    OBJECT              MESSAGE\n"
                "5m          Warning   BackOff   pod/nano-vector-0   Back-off restarting failed container vector\n")
        rows = support.parse_k8s_events(text, dt.datetime(2026, 11, 23, 12, 0, 0))
        self.assertEqual(rows[0]["ts"], "2026-11-23 11:55:00.000000")
        self.assertEqual(rows[0]["reason"], "BackOff")

    def test_containers_and_template_error(self):
        text = ("## nano-api\nservice=nano-api restarts=3 oom=true exit=137 started=a finished=b error=\n"
                "health=healthy failing_streak=0\nmem_limit=100 nano_cpus=1\n\n"
                "## nano-vector\n\n[stderr] template parsing error: map has no entry for key \"Health\"\n")
        rows = support.parse_containers(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["restarts"], rows[0]["oom_killed"], rows[0]["exit_code"]), (3, True, 137))

    def test_prometheus(self):
        rows = support.parse_prometheus('# HELP x\nnanosiem_vector_component_errors_total{component_id="ch",'
                                        'error_type="request_failed"} 4 1795439864078\n')
        self.assertEqual(rows[0]["labels"]["error_type"], "request_failed")
        self.assertEqual(rows[0]["value"], 4.0)

    def test_tsv_and_psql_footer(self):
        rows = support.tsv_rows("applied\thead\tfailed\n336\t397\t0\n(1 row)\n")
        self.assertEqual(rows, [{"applied": 336, "head": 397, "failed": 0}])


class SampleBundleTests(unittest.TestCase):
    def check(self, b):
        services = {r["service"] for r in b.logs}
        self.assertTrue({"api", "jobs", "vector", "clickhouse"} <= services, services)
        self.assertTrue(all(r["ts"] for r in b.logs))
        facts = {f["key"]: f["value"] for f in b.facts}
        self.assertEqual(facts["manifest.version"], "2.0.34")
        self.assertEqual(facts["env.LICENSE_TOKEN"], "[REDACTED]")
        crash = [r for r in b.logs if r["service"] == "vector" and "Configuration error" in r["message"]]
        self.assertEqual(len(crash), 5)
        live = [p for p in b.probes if p["name"] == "containers" and p["source"] == "live"]
        self.assertEqual(live[0]["value"]["exit_code"], 78)
        names = {p["name"] for p in b.probes}
        for n in ("compose:compose ps", "clickhouse:errors-recent", "postgres:migrations", "pg-licensing-state",
                  "logs-summary", "disk:data directories (is each its own mount?)"):
            self.assertIn(n, names)
        ps = [p for p in b.probes if p["name"] == "compose:compose ps"]
        self.assertTrue(any(p["value"].get("STATUS", "").startswith("Restarting (78)") for p in ps))
        self.assertEqual(b.notes, [])

    def test_directory(self):
        self.check(support.Bundle.from_path(FIXTURE))

    def test_nested_archives(self):
        """support collect's wrapper: bundle/<nano archive>.tar.gz + probes/probes.json."""
        with tempfile.TemporaryDirectory() as d:
            nano = os.path.join(d, "nano-support-nano-1-20261123T140000Z.tar.gz")
            with tarfile.open(nano, "w:gz") as t:
                t.add(os.path.join(FIXTURE, "nano-support-nano-1-20261123T140000Z"),
                      arcname="nano-support-nano-1-20261123T140000Z")
            with open(nano, "rb") as fh:
                nano_bytes = fh.read()
            with open(os.path.join(FIXTURE, "probes", "probes.json"), "rb") as fh:
                probes = fh.read()
            wrapper = os.path.join(d, "support-nano-1.tar.gz")
            support.wrap_archive(wrapper, {"bundle/" + os.path.basename(nano): nano_bytes,
                                           "probes/probes.json": probes})
            self.check(support.Bundle.from_path(wrapper))
            # a plain nano bundle loads too (no probes)
            b = support.Bundle.from_path(nano)
            self.assertTrue(b.logs)
            self.assertFalse([p for p in b.probes if p["source"] == "live"])


if __name__ == "__main__":
    unittest.main()
