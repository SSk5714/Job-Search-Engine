"""Backups of everything that matters: the database (pg_dump custom format) and the generated
documents (CVs, letters, evidence screenshots), with a manifest of checksums and row counts.

    python -m jobpilot.ops backup            # make one now
    python -m jobpilot.ops list
    python -m jobpilot.ops verify NAME       # checksums, archive and dump readable
    python -m jobpilot.ops restore NAME --yes

A backup is written to a temporary folder and renamed into place only when complete, so a
half-written backup never looks valid. A restore first verifies the backup, then makes a
`pre_restore` backup of the current state, then restores and compares row counts with the
manifest. Backups contain personal data: keep the backup folder private and copy it off the
server (see docs/operations.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal, reset_engine

FORMAT = "jobpilot-backup-v1"
COUNTED = ["users", "profile_versions", "profile_facts", "search_configs", "jobs", "job_match_evaluations",
           "applications", "application_state_history", "documents", "form_fields", "approvals",
           "submission_attempts", "follow_ups", "notifications"]


class BackupError(Exception):
    pass


def _root() -> Path:
    p = Path(get_settings().backup_dir)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)  # personal data: owner only
    except OSError:
        pass
    return p


def _libpq_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(db) -> dict[str, int]:
    return {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in COUNTED}


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, **kw)
    if res.returncode != 0:
        raise BackupError(f"{Path(cmd[0]).name} failed: {(res.stderr or res.stdout).strip()[-800:]}")
    return res


@dataclass
class BackupInfo:
    name: str
    path: Path
    manifest: dict


def create(kind: str = "manual") -> BackupInfo:
    s = get_settings()
    now = datetime.now(UTC)
    name = f"jobpilot-{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z-{kind}"
    root = _root()
    row_id = None
    with SessionLocal() as db:
        row = m.Backup(name=name, kind=kind, status="running", detail={})
        db.add(row)
        db.commit()
        row_id = row.id
    tmp = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=root))
    try:
        dump = tmp / "database.dump"
        _run([s.pg_dump_path, "--format=custom", "--no-owner", "--no-privileges", f"--file={dump}", _libpq_url()])
        docs_src = Path(s.documents_dir)
        docs_tar = tmp / "documents.tar.gz"
        files = 0
        with tarfile.open(docs_tar, "w:gz") as tar:
            if docs_src.exists():
                for p in sorted(docs_src.rglob("*")):
                    if p.is_file():
                        tar.add(p, arcname=str(p.relative_to(docs_src)))
                        files += 1
        with SessionLocal() as db:
            counts = _counts(db)
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        manifest = {"format": FORMAT, "name": name, "kind": kind, "created_at": now.isoformat(),
                    "alembic_revision": revision, "row_counts": counts, "document_files": files,
                    "files": {f.name: {"sha256": _sha256(f), "bytes": f.stat().st_size} for f in (dump, docs_tar)}}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
        final = root / name
        tmp.rename(final)  # atomic: a backup folder without a dot prefix is complete
        size = sum(f.stat().st_size for f in final.iterdir())
        with SessionLocal() as db:
            row = db.get(m.Backup, row_id)
            row.status, row.finished_at, row.size_bytes = "ok", datetime.now(UTC), size
            row.detail = {"row_counts": counts, "document_files": files, "revision": revision}
            db.commit()
        if kind == "scheduled":
            prune(s.backup_keep)
        return BackupInfo(name, final, manifest)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            with SessionLocal() as db:
                row = db.get(m.Backup, row_id)
                row.status, row.finished_at = "failed", datetime.now(UTC)
                row.detail = {"error": str(e)[:1000]}
                db.commit()
        except Exception:
            pass
        raise


def list_backups() -> list[BackupInfo]:
    out = []
    for p in sorted(_root().iterdir(), reverse=True):
        mf = p / "manifest.json"
        if p.is_dir() and not p.name.startswith(".") and mf.exists():
            try:
                out.append(BackupInfo(p.name, p, json.loads(mf.read_text())))
            except ValueError:
                continue
    return out


def _find(name: str) -> BackupInfo:
    if "/" in name or name.startswith("."):
        raise BackupError("Invalid backup name")
    for b in list_backups():
        if b.name == name:
            return b
    raise BackupError(f"No complete backup named {name}")


def verify(name: str) -> dict:
    """Checksums match, the dump is readable by pg_restore, the archive opens."""
    b = _find(name)
    if b.manifest.get("format") != FORMAT:
        raise BackupError("Unknown backup format")
    for fname, meta in b.manifest["files"].items():
        f = b.path / fname
        if not f.exists():
            raise BackupError(f"{fname} is missing")
        if _sha256(f) != meta["sha256"]:
            raise BackupError(f"{fname} is corrupt (checksum mismatch)")
    toc = _run([get_settings().pg_restore_path, "--list", str(b.path / "database.dump")]).stdout
    with tarfile.open(b.path / "documents.tar.gz") as tar:
        members = [x for x in tar.getmembers() if x.isfile()]
    if len(members) != b.manifest["document_files"]:
        raise BackupError("Document archive is incomplete")
    return {"name": name, "ok": True, "tables_in_dump": toc.count(" TABLE DATA "), "document_files": len(members)}


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if dest not in target.parents and target != dest:
            raise BackupError(f"Unsafe path in archive: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise BackupError(f"Links and devices are not allowed in the archive: {member.name}")
    tar.extractall(dest, filter="data")


def restore(name: str) -> dict:
    """Replace the database and documents with a backup. Makes a pre_restore backup first."""
    s = get_settings()
    verify(name)
    b = _find(name)
    # Unpack the documents first: if the archive is bad, nothing has been touched yet.
    docs = Path(s.documents_dir)
    docs.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=docs.parent))
    try:
        with tarfile.open(b.path / "documents.tar.gz") as tar:
            _safe_extract(tar, staging)
        safety = create("pre_restore")
        # database: drop everything in the public schema, then restore inside one transaction
        reset_engine()
        with SessionLocal() as db:
            db.execute(text("DROP SCHEMA public CASCADE"))
            db.execute(text("CREATE SCHEMA public"))
            db.commit()
        reset_engine()
        _run([s.pg_restore_path, "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error",
              f"--dbname={_libpq_url()}", str(b.path / "database.dump")])
        # documents: replace the folder's contents in place (it is often a mounted volume and cannot be renamed)
        for child in docs.iterdir():
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        for child in staging.iterdir():
            shutil.move(str(child), str(docs / child.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    with SessionLocal() as db:
        counts = _counts(db)
        mismatched = {t: (counts[t], b.manifest["row_counts"].get(t)) for t in COUNTED
                      if counts[t] != b.manifest["row_counts"].get(t)}
        db.add(m.Backup(name=f"restore-{datetime.now(UTC):%Y%m%dT%H%M%SZ}", kind="restore",
                        status="verified" if not mismatched else "failed", finished_at=datetime.now(UTC),
                        detail={"restored": name, "safety_backup": safety.name, "mismatched": mismatched}))
        db.commit()
    if mismatched:
        raise BackupError(f"Row counts differ after restore: {mismatched}. The state before the restore is in "
                          f"backup {safety.name}.")
    return {"restored": name, "safety_backup": safety.name, "row_counts": counts}


def prune(keep: int) -> list[str]:
    """Keep the newest `keep` scheduled backups; manual and pre_restore backups are never pruned."""
    scheduled = [b for b in list_backups() if b.manifest.get("kind") == "scheduled"]
    removed = []
    for b in scheduled[keep:]:
        shutil.rmtree(b.path, ignore_errors=True)
        removed.append(b.name)
    return removed


def last_ok(db) -> m.Backup | None:
    return db.scalar(select(m.Backup).where(m.Backup.status == "ok", m.Backup.kind.in_(["scheduled", "manual"]))
                     .order_by(m.Backup.started_at.desc()).limit(1))
