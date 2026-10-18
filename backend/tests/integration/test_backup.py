"""Backup and recovery drill: back up real data, lose it, restore it, prove it is identical."""

import hashlib
import json
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from jobpilot.config import get_settings
from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal, reset_engine
from jobpilot.ops import backup
from jobpilot.orchestrator.scheduler import tick

from tests.conftest import documents_ready_app


def _doc_hashes() -> dict[str, str]:
    root = Path(get_settings().documents_dir)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _table_digest() -> dict[str, str]:
    with SessionLocal() as db:
        return {t: db.scalar(text(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x"))
                for t in ("applications", "documents", "profile_facts", "jobs", "job_match_evaluations",
                          "application_state_history")}


def test_restore_drill_brings_back_identical_data(api):
    app_id = documents_ready_app(api)
    before_rows, before_docs = _table_digest(), _doc_hashes()
    assert len(before_docs) >= 4  # CV and letter, PDF and DOCX

    b = backup.create("manual")
    assert backup.verify(b.name)["ok"]
    assert b.manifest["row_counts"]["applications"] > 0

    # disaster: data deleted and a document destroyed
    with SessionLocal() as db:
        db.execute(text("TRUNCATE applications, jobs CASCADE"))
        db.commit()
    root = Path(get_settings().documents_dir)
    next(root.rglob("*.pdf")).unlink()
    assert _table_digest() != before_rows

    out = backup.restore(b.name)
    reset_engine()
    assert _table_digest() == before_rows
    assert _doc_hashes() == before_docs
    assert out["safety_backup"].endswith("pre_restore")
    with SessionLocal() as db:
        r = db.scalar(select(m.Backup).where(m.Backup.kind == "restore"))
        assert r.status == "verified" and r.detail["restored"] == b.name
    assert api.get(f"/applications/{app_id}").status_code in (200, 401)  # app still serves after restore


def test_corrupt_backup_is_refused_before_anything_is_touched(api):
    b = backup.create("manual")
    dump = b.path / "database.dump"
    dump.write_bytes(dump.read_bytes()[:-100] + b"x" * 100)
    with pytest.raises(backup.BackupError, match="checksum"):
        backup.restore(b.name)
    with SessionLocal() as db:
        assert db.scalar(select(m.Backup.id).where(m.Backup.kind == "pre_restore")) is None


def test_archive_with_path_traversal_is_refused(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        f = tmp_path / "x.txt"
        f.write_text("x")
        tar.add(f, arcname="../../escaped.txt")
    with tarfile.open(evil) as tar, pytest.raises(backup.BackupError, match="Unsafe"):
        backup._safe_extract(tar, tmp_path / "dest")


def test_half_written_backups_are_invisible(api):
    root = Path(get_settings().backup_dir)
    (root / ".jobpilot-20260101T000000Z-manual-tmp").mkdir()
    (root / "jobpilot-not-finished").mkdir()  # no manifest
    names = [b.name for b in backup.list_backups()]
    assert not any("not-finished" in n or n.startswith(".") for n in names)


def test_scheduled_backup_runs_once_a_day_and_prunes(api, monkeypatch):
    monkeypatch.setenv("JOBPILOT_BACKUP_AT", "00:00")
    monkeypatch.setenv("JOBPILOT_BACKUP_KEEP", "2")
    get_settings.cache_clear()
    try:
        out = tick(enqueue=lambda rid: None)
        assert "created" in out["backup"]
        assert tick(enqueue=lambda rid: None)["backup"] == {}  # already done today
        for _ in range(3):  # older scheduled backups beyond `keep` are pruned
            backup.create("scheduled")
        assert len([b for b in backup.list_backups() if b.manifest["kind"] == "scheduled"]) == 2
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_backup_failure_raises_an_alert(api, monkeypatch):
    monkeypatch.setenv("JOBPILOT_BACKUP_AT", "00:00")
    monkeypatch.setenv("JOBPILOT_PG_DUMP_PATH", "/nonexistent/pg_dump")
    get_settings.cache_clear()
    try:
        assert "failed" in tick(enqueue=lambda rid: None)["backup"]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    a = next(a for a in api.get("/alerts").json() if a["alert_key"] == "backup:failed")
    assert a["severity"] == "critical" and "jobpilot.ops backup" in a["remediation"]


def test_monitor_warns_when_backups_are_stale(api, monkeypatch):
    from jobpilot.monitor import service

    monkeypatch.setenv("JOBPILOT_BACKUP_AT", "03:15")
    get_settings.cache_clear()
    with SessionLocal() as db:
        db.add(m.Backup(name="old", kind="scheduled", status="ok", started_at=datetime.now(UTC) - timedelta(days=3)))
        db.commit()
    try:
        service.run_once()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    keys = [a["alert_key"] for a in api.get("/alerts").json()]
    assert "mon:backup:stale" in keys


def test_backup_api(api):
    r = api.post("/backups", key=None)
    assert r.status_code == 201 and r.json()["status"] == "ok"
    listed = api.get("/backups").json()
    assert listed["last_ok"]["name"] == r.json()["name"] and "restore" in listed["restore_hint"]
    manifest = json.loads((Path(get_settings().backup_dir) / r.json()["name"] / "manifest.json").read_text())
    assert manifest["format"] == "jobpilot-backup-v1"
