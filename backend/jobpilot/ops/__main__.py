"""Operations CLI: backups and restores. Run inside the API container or a local checkout."""

import argparse
import json
import sys

from jobpilot.ops import backup


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m jobpilot.ops")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup", help="make a backup now")
    sub.add_parser("list", help="list complete backups")
    v = sub.add_parser("verify", help="check a backup's checksums and readability")
    v.add_argument("name")
    r = sub.add_parser("restore", help="replace the database and documents with a backup")
    r.add_argument("name")
    r.add_argument("--yes", action="store_true", help="confirm: current data is replaced (a safety backup is made)")
    h = sub.add_parser("alive", help="exit 0 if a component's heartbeat is fresh (container healthchecks)")
    h.add_argument("component", choices=["scheduler", "monitor"])
    a = p.parse_args()
    if a.cmd == "alive":
        from jobpilot.db.heartbeat import age
        from jobpilot.db.session import SessionLocal

        with SessionLocal() as db:
            hb, seconds = age(db, a.component)
        fresh = hb is not None and seconds <= 3 * hb.interval_s
        print(f"{a.component}: " + (f"last beat {int(seconds)}s ago" if hb else "no heartbeat yet"))
        return 0 if fresh else 1
    try:
        if a.cmd == "backup":
            b = backup.create("manual")
            print(json.dumps({"name": b.name, "path": str(b.path), "row_counts": b.manifest["row_counts"]}, indent=2))
        elif a.cmd == "list":
            for b in backup.list_backups():
                print(f"{b.name}\t{b.manifest['kind']}\t{b.manifest['created_at']}\t"
                      f"{sum(f['bytes'] for f in b.manifest['files'].values()) // 1024} KiB")
        elif a.cmd == "verify":
            print(json.dumps(backup.verify(a.name), indent=2))
        elif a.cmd == "restore":
            if not a.yes:
                print("Restoring replaces ALL current data with the backup. A safety backup is made first.\n"
                      "Stop the api, worker, beat and monitor services, then re-run with --yes.", file=sys.stderr)
                return 2
            print(json.dumps(backup.restore(a.name), indent=2))
    except backup.BackupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
