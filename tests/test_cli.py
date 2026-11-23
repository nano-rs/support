#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""support collect end to end on a fake Compose install with a stub `docker` (no Docker daemon).

Checks consent (nothing written without a yes), the output file (0600, both parts), and that
secrets from .env and secret-shaped text in logs and probes never reach the file.
"""
from __future__ import annotations

import filecmp
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

from helpers import ROOT, nano_tool_path, support

CH_PASSWORD = "chAdm1n-S3cret-Value-77"
LICENSE = "Zk3q9V_r8XyT2mN4pL6sA1bC5dE7fG9hJ0kQwErTyUi"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfMDEiLCJleHAiOjE5MDAwMDAwMDB9"
       ".c2lnbmF0dXJlLXZhbHVlLWhlcmUtMTIzNDU2Nzg5MA")

STUB = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import json, sys
    a = sys.argv[1:]
    CH, LIC, JWT = %r, %r, %r
    containers = [
        {"Name": "nano-api", "Service": "nano-api", "State": "running", "Health": "healthy", "Status": "Up 2 days", "Image": "ghcr.io/nano-rs/nano-api:2.0.34"},
        {"Name": "nano-clickhouse", "Service": "clickhouse", "State": "running", "Health": "healthy", "Status": "Up", "Image": "clickhouse/clickhouse-server:26.10"},
        {"Name": "nano-postgres", "Service": "postgres", "State": "running", "Health": "healthy", "Status": "Up", "Image": "postgres:17"},
        {"Name": "nano-vector", "Service": "vector", "State": "restarting", "Health": "", "Status": "Restarting (78) 3 seconds ago", "Image": "ghcr.io/nano-rs/vector:0.61.0"},
        {"Name": "nano-vector-netns", "Service": "vector-netns", "State": "running", "Health": "", "Status": "Up", "Image": "nginx:alpine"},
    ]
    if a[:1] == ["compose"]:
        if "ps" in a and "json" in a:
            print("\n".join(json.dumps(c) for c in containers))
        elif "ps" in a:
            print("NAME          SERVICE   STATUS")
            for c in containers:
                print(f"{c['Name']:<13} {c['Service']:<9} {c['Status']}")
        sys.exit(0)
    if a[:1] == ["logs"]:
        name = a[-1]
        if name == "nano-vector":
            print('2026-11-23T13:20:52.215782Z 2026-11-23T13:20:52.215761Z ERROR vector::cli: Configuration error. error=Input "x" for transform "y" doesn\'t match any components.')
        else:
            print(f"2026-11-23T13:00:00.000000001Z 2026-11-23T13:00:00.000000Z  INFO service{{service.name=\"x\"}}: nanosiem_api: connecting with password={CH} token {LIC}")
            print(f"2026-11-23T13:00:01.000000001Z 2026-11-23T13:00:01.000000Z  WARN service{{service.name=\"x\"}}: nanosiem_api: session {JWT} expired")
        sys.exit(0)
    if a[:1] == ["inspect"]:
        if "--format" in a:
            print("ok")
            sys.exit(0)
        out = []
        for c in containers:
            if c["Name"] in a:
                out.append({"Name": "/" + c["Name"], "RestartCount": 41 if c["Service"] == "vector" else 0,
                            "State": {"OOMKilled": False, "ExitCode": 78 if c["Service"] == "vector" else 0,
                                      "Restarting": c["State"] == "restarting", "StartedAt": "x", "FinishedAt": "y"},
                            "HostConfig": {"Memory": 0, "RestartPolicy": {"Name": "unless-stopped"}}})
        print(json.dumps(out))
        sys.exit(0)
    if a[:1] == ["exec"]:
        joined = " ".join(a)
        if "clickhouse-client" in joined or "nano-clickhouse" in a:
            print("name\tcode\tvalue\tlast_error_time\tlast_error_message")
            print(f"AUTHENTICATION_FAILED\t516\t2\t2026-11-23 13:00:00\tpassword {CH} is incorrect, see {JWT}")
            sys.exit(0)
        if "psql" in joined:
            print("version\tdescription\tsuccess\n397\tx\tt\n(1 row)")
            sys.exit(0)
        if "8686/graphql" in joined:
            print("wget: can't connect to remote host (127.0.0.1): Connection refused")
            sys.exit(1)
        if "health" in joined or "ready" in joined:
            print('{"status":"ok"}')
            sys.exit(0)
        print("")
        sys.exit(0)
    if a[:1] in (["info"], ["version"], ["stats"], ["volume"], ["ps"]):
        sys.exit(0)
    sys.exit(0)
''') % (CH_PASSWORD, LICENSE, JWT)


class CollectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="support-test-")
        cls.install = os.path.join(cls.tmp, "nano")
        os.makedirs(os.path.join(cls.install, "scripts"))
        with open(nano_tool_path(), "rb") as src, \
                open(os.path.join(cls.install, "scripts", "nano-support-bundle"), "wb") as dst:
            dst.write(src.read())
        with open(os.path.join(cls.install, ".env"), "w") as fh:
            fh.write(f"NANO_VERSION=2.0.34\nNANO_EDITION=open\nCLICKHOUSE_ADMIN_PASSWORD={CH_PASSWORD}\n"
                     f"LICENSE_TOKEN={LICENSE}\nNANO_LICENSE_MODE=online\n")
        open(os.path.join(cls.install, "docker-compose.opensource.yml"), "w").close()
        bindir = os.path.join(cls.tmp, "bin")
        os.makedirs(bindir)
        stub = os.path.join(bindir, "docker")
        with open(stub, "w") as fh:
            fh.write(STUB.lstrip())
        os.chmod(stub, 0o755)
        cls.env = {**os.environ, "PATH": bindir + os.pathsep + os.environ.get("PATH", ""), "HOME": cls.tmp}

    def collect(self, out_dir: str, *extra: str):
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "support"), "collect",
                               "--install-dir", self.install, "--since", "1h", "--out-dir", out_dir, *extra],
                              env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)

    def test_no_consent_writes_nothing(self):
        out = os.path.join(self.tmp, "out-no")
        p = self.collect(out)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("answering no", p.stderr)
        self.assertFalse(os.path.exists(out) and os.listdir(out))

    def test_collect_with_consent(self):
        out = os.path.join(self.tmp, "out-yes")
        p = self.collect(out, "--yes")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        files = os.listdir(out)
        self.assertEqual(len(files), 1)
        path = os.path.join(out, files[0])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertIn("Preview of", p.stderr)
        texts = dict(support.archive_texts(path))
        names = sorted(texts)
        self.assertTrue(any(n.startswith("bundle/") and n.endswith("/MANIFEST.json") for n in names), names)
        self.assertIn("probes/probes.json", names)
        blob = "\n".join(texts.values())
        for secret in (CH_PASSWORD, LICENSE, JWT[:40]):
            self.assertNotIn(secret, blob)
        self.assertIn("[REDACTED", blob)
        # ...and the lines that held them were collected (so the check above means something).
        self.assertIn("nanosiem_api: connecting with password=[REDACTED", blob)
        self.assertIn("AUTHENTICATION_FAILED", texts["probes/probes.json"])
        # The live probes saw the crash loop.
        b = support.Bundle.from_path(path)
        live = {p["value"].get("container"): p["value"] for p in b.probes
                if p["name"] == "containers" and p["source"] == "live"}
        self.assertEqual(live["nano-vector"]["restarts"], 41)
        self.assertEqual(live["nano-vector"]["exit_code"], 78)

    def test_collect_over_ssh_runs_nothing_from_the_host_locally(self):
        """--ssh with a stub ssh that runs the remote command here, in a separate HOME."""
        bindir = os.path.dirname(self.env["PATH"].split(os.pathsep)[0] + "/x")
        ssh_log = os.path.join(self.tmp, "ssh-argv.json")
        stub = os.path.join(bindir, "ssh")
        with open(stub, "w") as fh:
            fh.write(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json, subprocess, sys
                a = sys.argv[1:]
                with open({ssh_log!r}, "a") as fh:
                    fh.write(json.dumps(a) + "\\n")
                i = a.index("--")
                cmd = a[i + 2]
                sys.exit(subprocess.run(["sh", "-c", cmd]).returncode)
            """))
        os.chmod(stub, 0o755)
        out = os.path.join(self.tmp, "out-ssh")
        p = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "support"), "collect",
                            "--ssh", "nano@nano.example.com", "--install-dir", self.install, "--since", "1h",
                            "--out-dir", out, "--yes"], env=self.env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(ssh_log) as fh:
            calls = [json.loads(x) for x in fh]
        self.assertEqual(len(calls), 1)  # one connection: no fetch of the host's tool, no second trip
        self.assertEqual(calls[0][calls[0].index("--") + 1], "nano@nano.example.com")
        files = os.listdir(out)
        path = os.path.join(out, files[0])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        blob = "\n".join(t for _, t in support.archive_texts(path))
        self.assertNotIn(CH_PASSWORD, blob)
        self.assertIn("probes/probes.json", [n for n, _ in support.archive_texts(path)])
        self.assertIn("secret-looking text left after redaction: none found", p.stderr)

    def test_missing_tool_explains(self):
        p = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "support"), "collect",
                            "--install-dir", os.path.join(self.tmp, "nope")], env=self.env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("No nano support bundle tool", p.stderr)


class RepoTests(unittest.TestCase):
    def test_skill_scripts_match_bin(self):
        for skill in ("nano-support-collect", "nano-support-investigate"):
            copy = os.path.join(ROOT, "skills", skill, "scripts", "support")
            self.assertTrue(filecmp.cmp(os.path.join(ROOT, "bin", "support"), copy, shallow=False),
                            f"{copy} differs from bin/support: run `make sync`")

    def test_recipes_parse(self):
        path = os.path.join(ROOT, "skills", "nano-support-investigate", "references", "queries.sql")
        with open(path, encoding="utf-8") as fh:
            recipes = support.parse_recipes(fh.read())
        self.assertGreaterEqual(len(recipes), 20)
        for name, r in recipes.items():
            self.assertTrue(r["what"], name)
            self.assertIn("SELECT", r["sql"].upper(), name)
            for word in ("INSERT", "ALTER", "DROP", "TRUNCATE", "DELETE", "CREATE"):
                self.assertNotRegex(r["sql"].upper(), rf"\b{word}\b", f"{name} is not read-only")

    def test_runbooks_linked_from_skill(self):
        refs = os.path.join(ROOT, "skills", "nano-support-investigate", "references")
        with open(os.path.join(ROOT, "skills", "nano-support-investigate", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        for name in os.listdir(refs):
            if name.startswith("runbook-"):
                self.assertIn(f"references/{name}", skill)


if __name__ == "__main__":
    unittest.main()
