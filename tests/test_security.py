#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security properties: untrusted bundles (traversal, links, bombs), ssh argument injection,
pinned downloads, private file creation, and redaction edge cases."""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import unittest

from helpers import nano_tool, support


def tar_bytes(members: list) -> bytes:
    """members: [(TarInfo, bytes or None)]."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for info, data in members:
            if data is None:
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def reg(name: str) -> tarfile.TarInfo:
    return tarfile.TarInfo(name)


class UntrustedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def write(self, name: str, data: bytes) -> str:
        p = os.path.join(self.d, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def test_traversal_absolute_and_link_members_are_skipped(self):
        link = reg("nano-support-x/hosts/h/logs/link.log")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        hard = reg("nano-support-x/hosts/h/logs/hard.log")
        hard.type, hard.linkname = tarfile.LNKTYPE, "nano-support-x/ok.txt"
        p = self.write("t.tar.gz", tar_bytes([
            (reg("../../escape.txt"), b"bad"), (reg("/abs/path.txt"), b"bad"),
            (reg("nano-support-x/a/../../up.txt"), b"bad"), (link, None), (hard, None),
            (reg("nano-support-x/ok.txt"), b"good")]))
        names = [n for n, _ in support.archive_texts(p)]
        self.assertEqual(names, ["nano-support-x/ok.txt"])

    def test_nesting_bomb_is_refused(self):
        inner = tar_bytes([(reg("x.txt"), b"x")])
        for i in range(4):
            inner = tar_bytes([(reg(f"level{i}.tar.gz"), inner)])
        p = self.write("nest.tar.gz", inner)
        with self.assertRaises(support.BundleError):
            list(support.archive_texts(p))

    def test_total_size_bomb_is_refused(self):
        # 40 MiB of zeros compresses to ~40 KiB; with a 16 MiB cap it must stop, not load it all.
        p = self.write("bomb.tar.gz", tar_bytes([(reg(f"f{i}.log"), b"\0" * (10 * 2**20)) for i in range(4)]))
        self.assertLess(os.path.getsize(p), 1 * 2**20)
        old = support.MAX_TOTAL_BYTES
        support.MAX_TOTAL_BYTES = 16 * 2**20
        try:
            with self.assertRaises(support.BundleError):
                list(support.archive_texts(p))
        finally:
            support.MAX_TOTAL_BYTES = old

    def test_member_count_bomb_is_refused(self):
        p = self.write("many.tar.gz", tar_bytes([(reg(f"f{i}"), b"") for i in range(60)]))
        old = support.MAX_MEMBERS
        support.MAX_MEMBERS = 50
        try:
            with self.assertRaises(support.BundleError):
                list(support.archive_texts(p))
        finally:
            support.MAX_MEMBERS = old

    def test_not_a_tarball(self):
        p = self.write("junk.tar.gz", gzip.compress(b"not a tar file at all" * 100))
        with self.assertRaises(support.BundleError):
            list(support.archive_texts(p))

    def test_directory_bundle_never_follows_symlinks(self):
        outside = self.write("secret-outside.txt", b"PRIVATE-KEY-MATERIAL")
        root = os.path.join(self.d, "bundle")
        logs = os.path.join(root, "nano-support-x", "hosts", "h", "logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "nano-api.log"), "w") as fh:
            fh.write("2026-11-23T13:00:00Z INFO ok\n")
        os.symlink(outside, os.path.join(logs, "nano-evil.log"))
        os.symlink(self.d, os.path.join(root, "nano-support-x", "hosts", "linkdir"))
        b = support.Bundle.from_path(root)
        blob = json.dumps(b.logs) + json.dumps(b.probes)
        self.assertNotIn("PRIVATE-KEY-MATERIAL", blob)
        self.assertTrue(any("nano-evil.log" in n for n in b.notes), b.notes)
        self.assertEqual(len(b.logs), 1)


class SshInjectionTests(unittest.TestCase):
    def args(self, **kw):
        base = dict(ssh="nano@nano.example.com", ssh_port=None, ssh_identity=None, ssh_option=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_destination_cannot_be_an_option(self):
        for bad in ("-Jjump@host", "-oProxyCommand=x", "-v@host", "nano@-oProxyCommand=x", "a b@host",
                    "nano@host;id", "", "nano@host\nx"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                support.ssh_base(self.args(ssh=bad))

    def test_double_dash_before_destination(self):
        argv = support.ssh_base(self.args())
        self.assertEqual(argv[-2:], ["--", "nano@nano.example.com"])
        self.assertIn("BatchMode=yes", argv)

    def test_command_running_ssh_options_refused(self):
        for bad in ("ProxyCommand=/tmp/x", "LocalCommand=/tmp/x", "PermitLocalCommand=yes", "RemoteCommand=id",
                    "ProxyJump=evil", "Include=/tmp/x", "UserKnownHostsFile=/tmp/x y"):
            with self.subTest(opt=bad), self.assertRaises(SystemExit):
                support.ssh_base(self.args(ssh_option=[bad]))
        ok = support.ssh_base(self.args(ssh_option=["UserKnownHostsFile=~/.ssh/kh", "StrictHostKeyChecking=yes"]))
        self.assertIn("UserKnownHostsFile=~/.ssh/kh", ok)


    def test_user_connect_timeout_wins(self):
        argv = support.ssh_base(self.args(ssh_option=["ConnectTimeout=30"]))
        opts = [argv[i + 1] for i, a in enumerate(argv) if a == "-o"]
        self.assertEqual(opts[0], "BatchMode=yes")
        self.assertLess(opts.index("ConnectTimeout=30"), opts.index("ConnectTimeout=10"))  # ssh keeps the first


class PinnedDownloadTests(unittest.TestCase):
    def test_unknown_release_is_never_fetched(self):
        called = []
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            support.download_bundle_tool("9.9.9", d, fetch=lambda u: called.append(u) or b"")
        self.assertEqual(called, [])

    def test_hash_mismatch_is_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                support.download_bundle_tool("2.0.34", d, fetch=lambda u: b"import os  # tampered")
            self.assertEqual(os.listdir(d), [])

    def test_pinned_match_is_written_0600(self):
        from helpers import nano_tool_path
        with open(nano_tool_path(), "rb") as fh:
            real = fh.read()
        with tempfile.TemporaryDirectory() as d:
            path, digest = support.download_bundle_tool("2.0.34", d, fetch=lambda u: real)
            self.assertEqual(digest, support.KNOWN_BUNDLE_TOOL_SHA256["2.0.34"])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class PrivateFileTests(unittest.TestCase):
    def test_copy_private_is_0600_under_open_umask_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src")
            with open(src, "wb") as fh:
                fh.write(b"bundle")
            old = os.umask(0)
            try:
                dest = os.path.join(d, "out.tar.gz")
                support.copy_private(src, dest)
                self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o600)
                with self.assertRaises(FileExistsError):
                    support.copy_private(src, dest)
                target = os.path.join(d, "victim")
                with open(target, "w") as fh:
                    fh.write("keep")
                link = os.path.join(d, "link.tar.gz")
                os.symlink(target, link)
                with self.assertRaises(OSError):
                    support.copy_private(src, link)
                with open(target) as fh:
                    self.assertEqual(fh.read(), "keep")
            finally:
                os.umask(old)


class RedactionEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = nano_tool()

    def test_json_escaped_secret_is_removed(self):
        secret = 'MyS3cret"With\\Quote99'
        red = self.sb.Redactor()
        red.add_env({"CLICKHOUSE_ADMIN_PASSWORD": secret})

        class P:
            keep = support.Prober.keep

            def __init__(self):
                self.redact, self.out = red, {}
        p = P()
        p.keep("ch-errors", True, rows=[{"last_error_message": f"auth failed for {secret}"}],
               text=f"multi\nline {secret}", error=secret)
        dumped = json.dumps(p.out)
        self.assertNotIn(secret, json.dumps(p.out, ensure_ascii=False).replace("\\\\", "\\").replace('\\"', '"'))
        self.assertNotIn(json.dumps(secret)[1:-1], dumped)
        self.assertIn("[REDACTED", dumped)

    def test_quoted_literals_removed_from_error_columns(self):
        rows = support.ch_rows("name\tlast_error_message\tdatabase\n"
                               "CANNOT_PARSE_TEXT\tCannot parse string \\'alice@example.com\\' as UInt64\tnanosiem\n",
                               self.sb)
        self.assertNotIn("alice@example.com", json.dumps(rows))
        self.assertIn("[REDACTED:literal]", rows[0]["last_error_message"])
        self.assertEqual(rows[0]["database"], "nanosiem")  # non-text columns untouched

    def test_error_text_of_failed_probe_scrubbed(self):
        out = support.scrub_error_text("ERROR: invalid input syntax for type uuid: 'bob-secret-value'", self.sb)
        self.assertNotIn("bob-secret-value", out)

    def test_ch_errors_probe_is_windowed(self):
        sql = dict(support.ch_probe_queries(3600))["ch-errors"]
        self.assertIn("last_error_time > now() - INTERVAL 3600 SECOND", sql)


class KubeSecretSeedTests(unittest.TestCase):
    """load_secrets() with a real-shaped Secret list: values are replaced by exact match, the probe
    JSON survives nano's key=value pattern, and the second redaction pass finds nothing."""

    CH_PW = 'Ch"Adm1n\\pw-Example-7731'
    PG_URL = "postgres://nanosiem:Pg-Example-Pass-5512@nano-postgres:5432/nanosiem"
    LIC = "Zk3q9V_r8XyT2mN4pL6sA1bC5dE7fG9hJ0kQwErTyUi"

    def secrets_json(self):
        import base64

        def b(v):
            return base64.b64encode(v.encode()).decode()
        return json.dumps({"items": [
            {"metadata": {"name": "nano-clickhouse"}, "type": "Opaque",
             "data": {"admin-password": b(self.CH_PW), "user": b("nanosiem_admin")}},
            {"metadata": {"name": "nano-postgres"}, "type": "Opaque",
             "data": {"DATABASE_URL": b(self.PG_URL), "POSTGRES_PASSWORD": b("Pg-Example-Pass-5512")}},
            {"metadata": {"name": "nano-license"}, "type": "Opaque", "data": {"LICENSE_TOKEN": b(self.LIC)}},
            {"metadata": {"name": "nano-tls"}, "type": "kubernetes.io/tls",
             "data": {"tls.crt": b("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"),
                      "tls.key": b("-----BEGIN " + "PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n")}},
            {"metadata": {"name": "default-token-x"}, "type": "kubernetes.io/service-account-token",
             "data": {"token": b("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl")}},
            {"metadata": {"name": "sh.helm.release.v1.nano.v3"}, "type": "helm.sh/release.v1",
             "data": {"release": b("H4sIAAAAAAAAA" * 4)}},
        ]})

    def test_seeded_values_redacted_without_corrupting_probes(self):
        sb = nano_tool()
        kp = support.KubeProber(sb, argparse.Namespace(context=None, namespace="nano", since=3600), sb.Redactor())
        orig = support.run
        support.run = lambda cmd, timeout=0, input_text=None: (0, self.secrets_json(), "")
        try:
            kp.load_secrets()
        finally:
            support.run = orig
        seed = kp.out["redaction-seed"]
        self.assertNotIn("error", seed, seed)
        # admin-password, the URL's password, POSTGRES_PASSWORD, LICENSE_TOKEN; never the user name
        self.assertEqual(seed["rows"], [{"values_added": 4}])
        kp.keep("ch-errors@nano-clickhouse-0", True, rows=[
            {"name": "AUTHENTICATION_FAILED", "code": 516,
             "last_error_message": f"{self.CH_PW} is wrong for user nanosiem_admin from 192.0.2.10"},
            {"name": "NETWORK_ERROR", "code": 210, "last_error_message": f"dial {self.PG_URL} refused by peer"}],
            text=f"license {self.LIC} rejected at check-in")
        entry = kp.out["ch-errors@nano-clickhouse-0"]
        self.assertNotIn("error", entry, entry)
        dumped = json.dumps(kp.out)
        for secret in ("Adm1n", "Pg-Example-Pass-5512", self.LIC):
            self.assertNotIn(secret, dumped)
        msg = entry["rows"][0]["last_error_message"]
        self.assertTrue(msg.startswith("[REDACTED:K8S_VALUE]"), msg)
        self.assertTrue(msg.endswith("is wrong for user nanosiem_admin from 192.0.2.10"), msg)  # not truncated
        self.assertIn("refused by peer", entry["rows"][1]["last_error_message"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "k8s.tar.gz")
            doc = {"tool": "support", "kind": "probes", "host": "k8s:nano", "probes": kp.out}
            support.wrap_archive(path, {"probes/probes.json": (json.dumps(doc, indent=1) + "\n").encode()})
            self.assertEqual(support.secret_findings(path, sb), [])

    def check_class(self, key, value, secrets, kept=()):
        """Seeded from (key, value): each secret vanishes from an error line, each kept word stays."""
        sb = nano_tool()
        red = sb.Redactor()
        for v in support.secret_seed_values(key, value):
            red.add(v, "K8S_VALUE")
        for secret in secrets:
            line = f"auth failed with {secret} for nanosiem_admin at nano-ch.example.com:9000 (code 516)"
            out = red(line)
            self.assertNotIn(secret, out, (key, out))
            self.assertIn("for nanosiem_admin at nano-ch.example.com:9000 (code 516)", out, (key, out))
        for word in kept:
            self.assertEqual(red(f"user {word} signed in"), f"user {word} signed in", (key, word))

    def test_seed_classes(self):
        b64 = __import__("base64").b64encode
        cases = [
            ("access_key_id", "R2EXAMPLEKEYID0001", ["R2EXAMPLEKEYID0001"], ()),
            ("access-key-id", "MINIOEXAMPLEKEY01", ["MINIOEXAMPLEKEY01"], ()),
            ("key", "raw-base64-key-AAAABBBBCCCC==", ["raw-base64-key-AAAABBBBCCCC=="], ()),
            ("pass", "Short-Pass-01", ["Short-Pass-01"], ()),
            ("pwd", "Pwd-Example-0042", ["Pwd-Example-0042"], ()),
            ("license.txt", "Lic3nseOpaque_ExampleValue_123", ["Lic3nseOpaque_ExampleValue_123"], ()),
            ("license.jwt", "Opaque-Lic-Example-9988", ["Opaque-Lic-Example-9988"], ()),
            ("url", "postgres://nanosiem_admin:Url-Pass-Example-31@pg.example.com:5432/nanosiem",
             ["Url-Pass-Example-31"], ("nanosiem_admin",)),
            ("database_url", "postgres://u:P%40ss-Example-99@pg:5432/db", ["P%40ss-Example-99", "P@ss-Example-99"], ()),
            ("webhook_url", "https://hooks.example.com/services/T000/B000/SECRETPATHEXAMPLE",
             ["https://hooks.example.com/services/T000/B000/SECRETPATHEXAMPLE"], ()),
            ("connection", "Server=db.example.com;User Id=sa;Password=Conn-Pass-Example-3;",
             ["Conn-Pass-Example-3"], ("db.example.com",)),
            (".dockerconfigjson", json.dumps({"auths": {"registry.example.com": {
                "username": "robot-pull", "password": "Reg-Pass-Example-1",
                "auth": b64(b"robot-pull:Reg-Pass-Example-1").decode()}}}),
             ["Reg-Pass-Example-1", b64(b"robot-pull:Reg-Pass-Example-1").decode()], ("robot-pull",)),
            ("tls.key", "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
             "BKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n-----END PRIVATE KEY-----\n",
             ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASC", "BKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"], ()),
            ("ca.key", "-----BEGIN EC " + "PRIVATE KEY-----\nMHcCAQEEIExample0123Example+xy\n-----END EC PRIVATE KEY-----",
             ["MHcCAQEEIExample0123Example+xy"], ()),
            ("users.xml", "<clickhouse><users><nanosiem_admin>\n<password>Xml-Pass-Example-42</password>\n"
             "<networks><ip>::/0</ip></networks>\n</nanosiem_admin></users></clickhouse>", ["Xml-Pass-Example-42"], ()),
            ("config.yaml", "database: nanosiem\nuser: nanosiem_admin\npassword: Yaml-Pass-Example-7\n"
             "api_key = Ini-Key-Example-55\n", ["Yaml-Pass-Example-7", "Ini-Key-Example-55"], ("nanosiem_admin",)),
            ("credentials.json", json.dumps({"type": "service_account", "client_email": "x@example.com",
                                             "private_key_id": "0123456789abcdef0123", "token": "Json-Tok-Example-8"}),
             ["0123456789abcdef0123", "Json-Tok-Example-8"], ()),
        ]
        for key, value, secrets, kept in cases:
            with self.subTest(key=key):
                self.check_class(key, value, secrets, kept)

    def test_non_secret_keys_never_seeded(self):
        for key, value in (("username", "nanosiem_admin"), ("user", "nanosiem_admin"), ("host", "nano-ch.example.com"),
                           ("port", "90000000"), ("database", "nanosiem_prod"), ("bucket", "nano-cold-example"),
                           ("region", "us-example-1"), ("clickhouse-user", "nanosiem_ingest"), ("db_host", "pg.example.com"),
                           ("short", "abc")):
            with self.subTest(key=key):
                self.assertEqual(support.secret_seed_values(key, value), [])

    def test_failed_seed_is_not_a_finding(self):
        sb = nano_tool()
        kp = support.KubeProber(sb, argparse.Namespace(context=None, namespace="nano", since=3600), sb.Redactor())
        orig = support.run
        support.run = lambda cmd, timeout=0, input_text=None: (1, "", "Forbidden")
        try:
            kp.load_secrets()
        finally:
            support.run = orig
        self.assertFalse(kp.out["redaction-seed"]["ok"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "k8s.tar.gz")
            support.wrap_archive(path, {"probes/probes.json": json.dumps({"probes": kp.out}, indent=1).encode()})
            self.assertEqual(support.secret_findings(path, sb), [])

    def test_probe_names_and_row_keys_survive_nano_redactor(self):
        """Every probe name and row key the tool emits passes nano's redactor unchanged."""
        import re as _re
        red = nano_tool().Redactor()
        src = open(support.__file__ if hasattr(support, "__file__") else "bin/support").read()
        names = set(_re.findall(r'self\.keep\(f?"([a-z0-9-]+)', src)) | {n for n, _ in support.ch_probe_queries(60)} \
            | {n for n, _ in support.PG_PROBE_QUERIES}
        self.assertIn("redaction-seed", names)
        for n in sorted(names):
            line = f'  "{n}": {{'
            self.assertEqual(red(line), line, n)
        for key in ("values_added", "restarts", "oom_killed", "exit_code", "last_error_message", "latest_fail_reason",
                    "component_id", "state", "valid", "locked_reason", "grace_ends_at", "detail", "url"):
            line = f'     "{key}": 1,'
            self.assertEqual(red(line), line, key)


class KubeArgvTests(unittest.TestCase):
    def test_postgres_sql_is_dollar_one(self):
        kp = support.KubeProber(nano_tool(), argparse.Namespace(context=None, namespace="nano", since=3600),
                                nano_tool().Redactor())
        kp.pods = [{"name": "nano-postgres-0", "phase": "Running", "containers": [("postgres", "postgres:17")]}]
        seen = []
        orig = support.run
        support.run = lambda cmd, timeout=0, input_text=None: (seen.append(cmd) or (0, "a\n1\n(1 row)\n", ""))
        try:
            kp.postgres()
        finally:
            support.run = orig
        argv = seen[0]
        i = argv.index("-c", argv.index("--"))
        self.assertEqual(argv[i + 2], "sh")                       # $0
        self.assertEqual(argv[i + 3], support.PG_PROBE_QUERIES[0][1])  # $1 is the SQL
        # and sh really binds it that way
        out = subprocess.run(["sh", "-c", 'printf %s "$1"', "sh", "SELECT 1"], capture_output=True, text=True)
        self.assertEqual(out.stdout, "SELECT 1")

    def test_vector_probe_never_execs_into_vector(self):
        kp = support.KubeProber(nano_tool(), argparse.Namespace(context=None, namespace="nano", since=3600),
                                nano_tool().Redactor())
        kp.pods = [{"name": "nano-vector-0", "phase": "Running",
                    "containers": [("vector", "ghcr.io/nano-rs/vector:x"), ("config-consumer", "curl:8")]}]
        seen = []
        orig = support.run
        support.run = lambda cmd, timeout=0, input_text=None: (seen.append(cmd) or (1, "", "x"))
        try:
            kp.vector()
        finally:
            support.run = orig
        execs = [c for c in seen if "exec" in c]
        self.assertTrue(execs)
        for c in execs:
            self.assertEqual(c[c.index("-c") + 1], "config-consumer")
        self.assertTrue(any("--raw" in c for c in seen))


if __name__ == "__main__":
    unittest.main()
