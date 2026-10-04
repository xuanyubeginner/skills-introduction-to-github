"""SQLite storage for found jobs and the application tracker."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import Job

STATUSES = ["saved", "applied", "interview", "offer", "rejected", "withdrawn"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT NOT NULL REFERENCES jobs(uid),
    date_applied TEXT,
    status TEXT NOT NULL DEFAULT 'saved',
    status_date TEXT NOT NULL,
    cv_path TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);
"""


class DB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- jobs
    def upsert_job(self, job: Job) -> bool:
        """Insert or refresh a job. Returns True if it is new."""
        row = self.conn.execute("SELECT 1 FROM jobs WHERE uid=?", (job.uid,)).fetchone()
        data = json.dumps(job.to_dict(), ensure_ascii=False)
        if row:
            self.conn.execute("UPDATE jobs SET data=? WHERE uid=?", (data, job.uid))
        else:
            self.conn.execute("INSERT INTO jobs VALUES (?,?,?)", (job.uid, date.today().isoformat(), data))
        self.conn.commit()
        return row is None

    def get_job(self, uid: str) -> Job:
        row = self.conn.execute("SELECT data FROM jobs WHERE uid LIKE ?", (uid + "%",)).fetchall()
        if len(row) != 1:
            raise KeyError(f"job id '{uid}' {'not found' if not row else 'is ambiguous'}")
        d = json.loads(row[0]["data"])
        d.pop("uid", None)
        return Job(**d)

    def jobs(self) -> list[tuple[str, Job]]:
        out = []
        for r in self.conn.execute("SELECT first_seen, data FROM jobs"):
            d = json.loads(r["data"])
            d.pop("uid", None)
            out.append((r["first_seen"], Job(**d)))
        return out

    # --- applications
    def add_application(self, job_uid: str, status: str = "applied", when: str | None = None,
                        cv_path: str = "", notes: str = "") -> int:
        job = self.get_job(job_uid)
        when = when or date.today().isoformat()
        cur = self.conn.execute(
            "INSERT INTO applications (job_uid, date_applied, status, status_date, cv_path, notes) VALUES (?,?,?,?,?,?)",
            (job.uid, when if status != "saved" else None, status, when, cv_path, notes),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_application(self, app_id: int, status: str, notes: str | None = None, when: str | None = None):
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        when = when or date.today().isoformat()
        sets = "status=?, status_date=?"
        args: list = [status, when]
        if status == "applied":
            sets += ", date_applied=COALESCE(date_applied, ?)"
            args.append(when)
        if notes is not None:
            sets += ", notes=?"
            args.append(notes)
        n = self.conn.execute(f"UPDATE applications SET {sets} WHERE id=?", (*args, app_id)).rowcount
        self.conn.commit()
        if not n:
            raise KeyError(f"application {app_id} not found")

    def applications(self, no_response_after_days: int = 21) -> list[dict]:
        rows = self.conn.execute(
            "SELECT a.*, j.data FROM applications a JOIN jobs j ON j.uid=a.job_uid ORDER BY a.date_applied DESC, a.id DESC"
        ).fetchall()
        out = []
        today = date.today()
        for r in rows:
            job = json.loads(r["data"])
            status = r["status"]
            if status == "applied" and r["date_applied"]:
                age = (today - datetime.fromisoformat(r["date_applied"]).date()).days
                if age >= no_response_after_days:
                    status = "no_response"
            out.append({
                "id": r["id"], "date_applied": r["date_applied"] or "", "status": status,
                "status_date": r["status_date"], "cv_path": r["cv_path"], "notes": r["notes"],
                "title": job["title"], "company": job["company"], "location": job["location"],
                "url": job["url"], "description": job["description"], "score": job.get("score", 0),
                "job_uid": job["uid"], "source": job["source"],
            })
        return out
