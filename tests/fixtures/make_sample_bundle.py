#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write tests/fixtures/sample-bundle: a SYNTHETIC support bundle in nano's real layout.

    python3 tests/fixtures/make_sample_bundle.py

Everything in it is made up: host names under example.com, addresses from the documentation
ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), no real secrets. The layout and line
formats match what `scripts/nano support-bundle` (nano 2.0.34, Compose single node) writes, so
the loader and the playbook queries can be tested without a real install.

Planted problems (each one is found by a playbook query in the skills):
  * Vector crash loop: a hand-added config file names an input that does not exist (exit 78).
  * ClickHouse Code 241 (memory limit) on a wide search, and Code 252 (too many parts).
  * License in its grace period, a license check-in failure.
  * An SSO sign-in refused by group admission.
  * A hunt sweep held because a data source stopped arriving.
  * An AI provider rejecting the API key.
"""
from __future__ import annotations

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sample-bundle")
TOP = "nano-support-nano-1-20261123T140000Z"
HOST = "nano-1"
ESC = "\x1b"


def ts(minute: int, second: int = 0, frac: str = "123456") -> str:
    return f"2026-11-23T13:{minute:02d}:{second:02d}.{frac}Z"


def docker(minute: int, second: int, body: str) -> str:
    """docker logs --timestamps prefix (nanoseconds) + the line the program printed."""
    return f"{ts(minute, second, '123456789')} {body}"


def rust(minute: int, second: int, level: str, target: str, msg: str, service: str = "nanosiem-api",
         color: bool = False) -> str:
    """tracing's plain one-line format, as nano's services print it on Compose."""
    span = f'service{{service.name="{service}" deployment_id= version="2.0.34"}}'
    lvl = f"{level:>5}"
    if color:  # the real Compose logs carry ANSI colors; the loader strips them
        return docker(minute, second, f"{ESC}[2m{ts(minute, second)}{ESC}[0m {ESC}[31m{lvl}{ESC}[0m "
                                      f"{ESC}[1m{span}{ESC}[0m: {ESC}[2m{target}{ESC}[0m: {msg}")
    return docker(minute, second, f"{ts(minute, second)} {lvl} {span}: {target}: {msg}")


def vec(minute: int, second: int, level: str, target: str, msg: str) -> str:
    return docker(minute, second, f"{ts(minute, second)} {level:>5} {target}: {msg}")


def files() -> dict:
    f: dict = {}
    h = f"hosts/{HOST}"
    f["MANIFEST.json"] = json.dumps({
        "tool": "nano support-bundle", "tool_version": "1", "created_utc": "2026-11-23T14:00:00Z",
        "mode": "Compose single node", "since_seconds": 86400, "max_log_mb": 20, "redactions": 31,
        "contains_event_data": False, "install_id": "inst_01jexampleexampleexample0", "version": "2.0.34",
        "edition": "enterprise", "inventory": None,
        "hosts": [{"name": HOST, "local": True, "ok": True, "notes": []}], "notes": [], "files": []}, indent=2)
    f["README.md"] = "# nano support bundle\n\n(synthetic fixture)\n"
    f["cluster/clock-skew.txt"] = f"collector\t{HOST}\t2026-11-23T14:00:00Z\nhost\tskew_s\trtt_s\tdetail\n" \
                                  "(single host: see host.txt 'time sync' for NTP state)\n"
    f[f"{h}/host.json"] = json.dumps({"host": HOST, "hostname": HOST, "epoch": 1795442400.0,
                                      "mode": "single-node", "roles": "", "install_id": "inst_01jexampleexampleexample0",
                                      "version": "2.0.34", "edition": "enterprise", "notes": []}, indent=2)
    f[f"{h}/host.txt"] = (f"## host\nhostname: {HOST}\nnano host name: {HOST}\ncollected_utc: 2026-11-23T14:00:00Z\n"
                          "install_dir: /home/nano/nano\nmode: single-node\nroles: app,ingest,clickhouse,postgres (single node)\n\n"
                          "## cpus\n8\n\n## memory\n               total        used        free\nMem:           31828       27410         512\n\n"
                          "## time sync\n               Local time: Mon 2026-11-23 14:00:00 UTC\nSystem clock synchronized: yes\n")
    f[f"{h}/release.txt"] = ("NANO_VERSION=2.0.34\nNANO_EDITION=enterprise\nNANO_SCHEMA_PROFILE=ocsf\n"
                             "NANO_DEPLOYMENT_ID=dep_01jexampleexampleexample0\nNANO_LICENSE_MODE=online\n")
    f[f"{h}/env.txt"] = ("CLICKHOUSE_ADMIN_PASSWORD=[REDACTED]\nCLICKHOUSE_MEM_LIMIT=6G\nLICENSE_TOKEN=[REDACTED]\n"
                         "LICENSE_URL=https://api.example.com\nNANO_BASE_URL=https://nano.example.com\n"
                         "NANO_DEPLOYMENT_ID=dep_01jexampleexampleexample0\nNANO_EDITION=enterprise\n"
                         "NANO_LICENSE_MODE=online\nNANO_VERSION=2.0.34\nPOSTGRES_PASSWORD=[REDACTED]\n")
    f[f"{h}/compose.txt"] = (
        "## compose ps\n"
        "NAME              IMAGE                                     COMMAND                  SERVICE        CREATED       STATUS                          PORTS\n"
        "nano-api          ghcr.io/nano-rs/nano-api:2.0.34           \"nanosiem-api\"           nano-api       2 days ago    Up 2 days (healthy)             3000/tcp\n"
        "nano-clickhouse   clickhouse/clickhouse-server:26.10        \"/entrypoint.sh\"         clickhouse     2 days ago    Up 2 days (healthy)             8123/tcp, 9000/tcp\n"
        "nano-jobs         ghcr.io/nano-rs/nano-jobs:2.0.34          \"nanosiem-jobs\"          nano-jobs      2 days ago    Up 2 days (healthy)             \n"
        "nano-postgres     postgres:17                               \"docker-entrypoint.s…\"   postgres       2 days ago    Up 2 days (healthy)             5432/tcp\n"
        "nano-search       ghcr.io/nano-rs/nano-search:2.0.34        \"nanosiem-search\"        nano-search    2 days ago    Up 2 days (healthy)             3002/tcp\n"
        "nano-vector       ghcr.io/nano-rs/vector:0.61.0-nano.13     \"/bin/sh /etc/vector…\"   vector         2 days ago    Restarting (78) 9 seconds ago   \n"
        "nano-vector-netns nginx:alpine                              \"/bin/sh -ec 'trap '…\"   vector-netns   2 days ago    Up 2 days                       0.0.0.0:8088->8088/tcp\n")
    # nano 2.0.34 writes a template error for containers without a health check (Vector among
    # them): the fixture keeps that, so the skills learn to fall back to compose ps and probes.
    f[f"{h}/containers.txt"] = (
        "## nano-api\nservice=nano-api restarts=0 oom=false exit=0 started=2026-11-21T09:00:00.000000000Z "
        "finished=0001-01-01T00:00:00Z error=\nhealth=healthy failing_streak=0\nmem_limit=2147483648 nano_cpus=2000000000\n\n"
        "## nano-clickhouse\nservice=clickhouse restarts=2 oom=true exit=137 started=2026-11-23T13:31:02.000000000Z "
        "finished=2026-11-23T13:30:58.000000000Z error=\nhealth=healthy failing_streak=0\nmem_limit=6442450944 nano_cpus=4000000000\n\n"
        "## nano-vector\n\n[stderr] template parsing error: template: :2:18: executing \"\" at <.State.Health>: "
        "map has no entry for key \"Health\"\n\n")
    f[f"{h}/disk.txt"] = ("## df -hT\nFilesystem     Type  Size  Used Avail Use% Mounted on\n/dev/sdb1      ext4  500G  471G   29G  95% /var/lib/docker\n\n"
                          "## data directories (is each its own mount?)\nwhat\tpath\tis_mountpoint\tmount_target\tsource\tfstype\tused\tfree\n"
                          "docker root\t/var/lib/docker\tyes\t/var/lib/docker\t/dev/sdb1\text4\t471.0G\t29.0G\n")
    f[f"{h}/vector.txt"] = ("## vector version\nvector 0.61.0 (x86_64-unknown-linux-gnu nano 0.61.0-nano.13)\n\n"
                            "## internal metrics (errors, discards, buffers, throughput)\n"
                            "Error response from daemon: container is restarting, wait until the container is running\n")
    f[f"{h}/postgres.txt"] = ("## install-identity\ninstall_id=inst_01jexampleexampleexample0\ncreated_at=2026-11-01 10:00:00+00\n\n"
                              "## migrations\napplied\thead\tfailed\n336\t397\t0\n(1 row)\n\n"
                              "## activity\nstate\twait_event_type\tcount\nidle\tClient\t20\nactive\t\t1\n(2 rows)\n")
    f[f"{h}/clickhouse.txt"] = (
        "## version\nversion\tuptime_s\thost\n26.10.4.207\t1738\tch-example\n\n"
        "## errors-recent\nname\tcode\tvalue\tlast_error_time\tremote\tlast_error_message\n"
        "MEMORY_LIMIT_EXCEEDED\t241\t14\t2026-11-23 13:30:55\t0\t(total) memory limit exceeded: would use 5.71 GiB (attempt to allocate chunk of 4.00 MiB), maximum: 5.70 GiB\n"
        "TOO_MANY_PARTS\t252\t3\t2026-11-23 13:42:10\t0\tToo many parts (3001 with average size of 12.10 KiB) in table \\'nanosiem.ocsf_logs_local (abcd)\\'. Merges are processing significantly slower than inserts\n"
        "NETWORK_ERROR\t210\t6\t2026-11-23 13:17:01\t0\tI/O error: Broken pipe, while writing to socket (192.0.2.10:8123 -> 192.0.2.11:42008)\n\n"
        "## parts-by-table\ndatabase\ttable\tactive_parts\trows\ton_disk\tmax_level\tpartitions\n"
        "nanosiem\tocsf_logs_local\t3012\t918223344\t402.11 GiB\t3\t30\n"
        "nanosiem\tsignals\t41\t120044\t31.20 MiB\t5\t9\n\n"
        "## parts-hot-partitions\ndatabase\ttable\tpartition\tactive_parts\nnanosiem\tocsf_logs_local\t20261123\t2961\n\n"
        "## disks\nname\tpath\tfree\ttotal\tused_pct\ttype\ndefault\t/var/lib/clickhouse/\t29.00 GiB\t500.00 GiB\t94.2\tLocal\n\n"
        "## merges\n(no rows)\n\n## mutations-pending\n(no rows)\n")
    f[f"{h}/logs/_summary.tsv"] = (
        "container\tservice\tbytes_seen\tbytes_kept\ttruncated\tfilter\n"
        "nano-api\tnano-api\t120000\t2400\tno\tfull, SQL literals and search text removed\n"
        "nano-vector\tvector\t40000\t900\tno\twarn/error only, payload removed\n"
        "nano-clickhouse\tclickhouse\t10000\t600\tno\twarn/error only, payload removed\n"
        "nano-jobs\tnano-jobs\t30000\t800\tno\tfull, SQL literals and search text removed\n"
        "nano-search\tnano-search\t30000\t800\tno\tfull, SQL literals and search text removed\n"
        "nano-postgres\tpostgres\t3000\t300\tno\tfull, SQL literals and search text removed\n"
        "\nnot collected (prints customer events): nano-vector-tap\n")
    api = [
        rust(10, 1, "INFO", "nanosiem_api", "Starting NanoSIEM API server", color=True),
        rust(10, 2, "INFO", "nanosiem_core::db::dual_pool", "ClickHouse database 'nanosiem' ready"),
        rust(12, 0, "ERROR", "nanosiem_core::license::checker",
             "License check failed (will retry next interval) error=connection timed out"),
        rust(30, 55, "ERROR", "nanosiem_search::executor",
             "search failed error=Code: 241. DB::Exception: (total) memory limit exceeded: would use 5.71 GiB, "
             "maximum: 5.70 GiB. (MEMORY_LIMIT_EXCEEDED) WHERE lower(message) ILIKE '[REDACTED:literal]'"),
        rust(31, 0, "ERROR", "nanosiem_search::executor",
             "search failed error=Code: 241. DB::Exception: (total) memory limit exceeded: would use 5.69 GiB, "
             "maximum: 5.70 GiB. (MEMORY_LIMIT_EXCEEDED)"),
        rust(35, 12, "WARN", "nanosiem_api::auth::oidc",
             "Rejected OIDC sign-in reason=group_not_allowed error=SSO account is not in a group allowed to sign in"),
        rust(40, 3, "WARN", "nanosiem_api::ai::provider",
             "direct AI endpoint returned an error status=401 error=Authentication failed: "
             "api.example.com answered HTTP 401: the API key was rejected"),
        rust(44, 9, "WARN", "nanosiem_api::middleware::rate_limit", "Login rate limit exceeded ip=198.51.100.23"),
        docker(45, 0, '{"timestamp":"2026-11-23T13:45:00.000001Z","level":"INFO","fields":{"message":'
                      '"Vector configuration validation passed","generation":12},'
                      '"target":"nanosiem_core::parsers::vector_config::deploy"}'),
    ]
    f[f"{h}/logs/nano-api.log"] = "\n".join(api) + "\n"
    jobs = [
        rust(12, 30, "WARN", "nanosiem_core::hunts::service",
             "hunt sweep held: telemetry readiness probe failed hunt=suspicious_powershell_download "
             "reason=Can't run yet: Windows process activity stopped arriving.", service="nanosiem-jobs"),
        rust(42, 11, "ERROR", "nanosiem_core::detection::service",
             "scheduled rule failed rule=dns_tunnel_long_labels error=Code: 252. DB::Exception: Too many parts "
             "(3001 with average size of 12.10 KiB) in table 'nanosiem.ocsf_logs_local'. (TOO_MANY_PARTS)",
             service="nanosiem-jobs"),
    ]
    f[f"{h}/logs/nano-jobs.log"] = "\n".join(jobs) + "\n"
    f[f"{h}/logs/nano-search.log"] = rust(10, 3, "INFO", "nanosiem_search", "ClickHouse schema version OK",
                                         service="nanosiem-search") + "\n"
    vector = []
    for minute in (51, 52, 53, 54, 55):
        vector.append(vec(minute, 5, "INFO", "vector::app", 'Loading configs. paths=["/etc/vector"]'))
        vector.append(vec(minute, 7, "ERROR", "vector::cli",
                          'Configuration error. error=Input "splunk_hec_ingst" for transform "drop_debug_events" '
                          "doesn't match any components. internal_log_rate_limit=false"))
    vector.append(docker(56, 0, "nano-vector: not starting Vector yet (its ports refuse connections, so nothing "
                                "is acknowledged): configuration does not build"))
    f[f"{h}/logs/nano-vector.log"] = "\n".join(vector) + "\n"
    ch = [
        docker(30, 55, "2026.11.23 13:30:55.120300 [ 812 ] {a1b2c3} <Error> executeQuery: Code: 241. DB::Exception: "
                       "(total) memory limit exceeded: would use 5.71 GiB. (MEMORY_LIMIT_EXCEEDED)"),
        docker(30, 58, "2026.11.23 13:30:58.000000 [ 1 ] {} <Fatal> Application: Child process was terminated by signal 9 (KILL). "
                       "If it is not done by 'forcestop' command or manually, the possible cause is OOM Killer"),
        docker(42, 10, "2026.11.23 13:42:10.441000 [ 77 ] {} <Error> nanosiem.ocsf_logs_local (abcd): Code: 252. "
                       "DB::Exception: Too many parts (3001). Merges are processing significantly slower than inserts. (TOO_MANY_PARTS)"),
    ]
    f[f"{h}/logs/nano-clickhouse.log"] = "\n".join(ch) + "\n"
    f[f"{h}/logs/nano-postgres.log"] = docker(5, 0, "2026-11-23 13:05:00.100 UTC [57] LOG:  database system is ready "
                                                    "to accept connections") + "\n"
    probes = {
        "tool": "support", "tool_version": "0.1.0", "kind": "probes", "collected_utc": "2026-11-23T14:00:05Z",
        "host": HOST, "since_seconds": 86400, "redactions": 4, "contains_event_data": False,
        "probes": {
            "containers": {"ok": True, "rows": [
                {"container": "nano-vector", "service": "vector", "state": "restarting",
                 "status": "Restarting (78) 9 seconds ago", "restarts": 41, "oom_killed": False, "exit_code": 78,
                 "restarting": True, "restart_policy": "unless-stopped"},
                {"container": "nano-clickhouse", "service": "clickhouse", "state": "running",
                 "status": "Up 29 minutes (healthy)", "restarts": 2, "oom_killed": True, "exit_code": 137,
                 "restarting": False, "restart_policy": "unless-stopped"},
                {"container": "nano-api", "service": "nano-api", "state": "running", "status": "Up 2 days (healthy)",
                 "restarts": 0, "oom_killed": False, "exit_code": 0, "restarting": False}]},
            "health": {"ok": True, "rows": [
                {"service": "nano-api", "url": "http://127.0.0.1:3000/health", "ok": True, "detail": '{"status":"ok"}'},
                {"service": "vector-netns", "url": "http://127.0.0.1:8686/health", "ok": False,
                 "detail": "wget: can't connect to remote host (127.0.0.1): Connection refused"}]},
            "vector-topology": {"ok": False, "text": "wget: can't connect to remote host (127.0.0.1): Connection refused",
                                "error": "Vector API did not answer (Vector is down or restarting, or its API is off)"},
            "ch-query-log-exceptions": {"ok": True, "rows": [
                {"exception_code": 241, "error_name": "MEMORY_LIMIT_EXCEEDED", "query_kind": "Select",
                 "user": "nanosiem_search", "queries": 14, "first_seen": "2026-11-23 13:28:01",
                 "last_seen": "2026-11-23 13:30:55"},
                {"exception_code": 252, "error_name": "TOO_MANY_PARTS", "query_kind": "Insert",
                 "user": "nanosiem_ingest", "queries": 3, "first_seen": "2026-11-23 13:41:00",
                 "last_seen": "2026-11-23 13:42:10"}]},
            "ch-query-log-slowest-shapes": {"ok": True, "rows": [
                {"normalized_query_hash": 1234567890123, "query_kind": "Select", "user": "nanosiem_search",
                 "queries": 22, "p50_ms": 8100, "p95_ms": 41000, "max_ms": 58800, "max_read_rows": 912000000,
                 "max_memory": 6120000000, "failed": 14, "exception_codes": [241, 0]}]},
            "vector-config-files": {"ok": True, "rows": [
                {"path": "00-base.toml", "bytes": 4210, "mode": "0o644", "modified_utc": "2026-11-21 09:00:00"},
                {"path": "02-hec-source.toml", "bytes": 1880, "mode": "0o644", "modified_utc": "2026-11-21 09:00:00"},
                {"path": "95-local-filter.toml", "bytes": 162, "mode": "0o644", "modified_utc": "2026-11-23 13:50:40"}]},
            "vector-config-local-changes": {"ok": True, "rows": [
                {"status": "??", "path": "config/vector/95-local-filter.toml"}]},
            "pg-migrations-failed": {"ok": True, "rows": []},
            "ch-migrations-recent": {"ok": True, "rows": [
                {"version": 397, "name": "397_example", "applied_at": "2026-11-21 09:00:01"}]},
            "disk-free": {"ok": True, "rows": [
                {"filesystem": "/dev/sdb1", "size": 536870912000, "used": 505732399104, "available": 31138512896,
                 "use_pct": 95, "mounted_on": "/var/lib/docker"}]},
            "pg-licensing-state": {"ok": True, "rows": [
                {"state": "grace_period", "valid": True, "tier": "enterprise", "locked_reason": None,
                 "grace_ends_at": "2026-11-30 00:00:00+00", "expires_at": None,
                 "last_checked_at": "2026-11-23 11:58:00+00"}]},
        },
    }
    f["probes/probes.json"] = json.dumps(probes, indent=1)
    return f


def main() -> None:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for name, text in files().items():
        top = "" if name.startswith("probes/") else TOP + "/"
        path = os.path.join(OUT, top + name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
