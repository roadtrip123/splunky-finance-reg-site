"""SQLite store. One connection per call, WAL, and explicit BEGIN IMMEDIATE where it matters.

Allocation is the only place correctness is subtle: two people pressing Claim at the same instant
must not be handed the same instance, so the read of the free list and the write that claims it sit
inside one write transaction rather than being two statements that happen to be next to each other.
"""
import csv
import io
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlparse

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS boxes (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'free',          -- free | assigned | held
  participant_id INTEGER,
  assigned_at REAL
);
CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  token TEXT NOT NULL UNIQUE,
  box_id INTEGER,
  galileo_email TEXT NOT NULL DEFAULT '',
  galileo_state TEXT NOT NULL DEFAULT 'queued', -- queued|creating|ready|failed|pool
  galileo_error TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'active',         -- active | released
  created_at REAL NOT NULL,
  ip TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pool (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'free',           -- free | issued
  participant_id INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
  participant_id INTEGER NOT NULL,
  step INTEGER NOT NULL,
  source TEXT NOT NULL,                         -- auto | self
  at REAL NOT NULL,
  PRIMARY KEY (participant_id, step, source)
);
CREATE TABLE IF NOT EXISTS probes (
  box_id INTEGER PRIMARY KEY,
  checked_at REAL NOT NULL,
  reachable INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  partial TEXT NOT NULL DEFAULT ''              -- steps under way, comma separated
);
CREATE INDEX IF NOT EXISTS boxes_state ON boxes(state);
CREATE INDEX IF NOT EXISTS participants_state ON participants(galileo_state);
"""

ACTIVE_GALILEO = ("queued", "creating", "ready")


class RegistrationClosed(Exception):
    """Raised when the account cap is reached, so the page can say so plainly."""


def connect():
    path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def writing():
    """A write transaction. BEGIN IMMEDIATE takes the lock up front, so a concurrent writer waits
    here rather than failing halfway through with 'database is locked'."""
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


# Columns added after the first version shipped. CREATE TABLE IF NOT EXISTS leaves an existing
# table alone, so an upgrade mid-event would otherwise run against a table missing a column.
ADDED_COLUMNS = {"participants": {"state": "TEXT NOT NULL DEFAULT 'active'",
                                   "galileo_password": "TEXT NOT NULL DEFAULT ''"}}


def init_db():
    db = connect()
    try:
        db.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            have = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    finally:
        db.close()


def log(db, kind, detail=""):
    db.execute("INSERT INTO events (at, kind, detail) VALUES (?,?,?)", (time.time(), kind, detail))


def normalise(email):
    return (email or "").strip().lower()


# ---------------------------------------------------------------- runtime settings

def get_config(key):
    """(value, updated_at) for a setting changed from the admin page, or (None, None)."""
    db = connect()
    try:
        row = db.execute("SELECT value, updated_at FROM config WHERE key=?", (key,)).fetchone()
        return (row["value"], row["updated_at"]) if row else (None, None)
    finally:
        db.close()


def set_config(key, value):
    with writing() as db:
        db.execute("INSERT INTO config (key, value, updated_at) VALUES (?,?,?)"
                   " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                   " updated_at=excluded.updated_at", (key, value, time.time()))
        # The event says that it changed, never what to.
        log(db, "config-changed", key)


# ---------------------------------------------------------------- boxes and pool

def add_boxes(rows):
    """rows: iterable of (url, label). Returns (added, duplicates). Re-uploading is safe: a URL
    already known is skipped rather than creating a second copy of the same instance."""
    added = duplicates = 0
    with writing() as db:
        for url, label in rows:
            url = (url or "").strip()
            if not url:
                continue
            try:
                db.execute("INSERT INTO boxes (url, label) VALUES (?,?)", (url, (label or "").strip()))
                added += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        log(db, "boxes-uploaded", f"added {added}, duplicates {duplicates}")
    if added:
        assign_waiting()
    return added, duplicates


def add_pool(emails):
    added = duplicates = 0
    with writing() as db:
        for email in emails:
            email = normalise(email)
            if not email:
                continue
            try:
                db.execute("INSERT INTO pool (email) VALUES (?)", (email,))
                added += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        log(db, "pool-uploaded", f"added {added}, duplicates {duplicates}")
    return added, duplicates


URL = re.compile(r"https?://[^\s,;\"'<>|]+", re.I)


def clean_url(value):
    """The value if it is nothing but an http(s) URL, otherwise "". Anything that reaches a
    participant passes through here, so a malformed row, which may carry an SSH password from the
    platform's export, is never shown to anyone."""
    value = (value or "").strip()
    if not URL.fullmatch(value):
        return ""
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    return value.rstrip(".")


def parse_csv(text):
    """Instance URLs from whatever the lab platform exported: comma, tab or semicolon separated,
    with or without a header, or a bare list one per line. Only the URL is kept. Other columns,
    such as sshPassword and sshUrl in the Splunk Show export, are read past and never stored."""
    lines = [line for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines:
        return []
    try:
        delimiter = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters=",\t;|").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in lines[0] else ","
    rows = list(csv.reader(lines, delimiter=delimiter))
    header = [cell.strip().lower() for cell in rows[0]]
    url_col = header.index("url") if "url" in header else None
    label_col = next((header.index(n) for n in ("label", "name") if n in header), None)
    found = []
    for row in rows:
        cells = [cell.strip() for cell in row]
        preferred = [cells[url_col]] if url_col is not None and url_col < len(cells) else []
        url = next((clean for clean in map(clean_url, preferred + cells) if clean), "")
        if url:
            label = cells[label_col] if label_col is not None and label_col < len(cells) else ""
            found.append((url, label))
    return found


def remove_box(box_id):
    """Take an instance off the list. Whoever had it goes back to waiting and is served the next
    free one, so removing a bad row never leaves someone holding nothing."""
    with writing() as db:
        db.execute("UPDATE participants SET box_id=NULL WHERE box_id=?", (box_id,))
        db.execute("DELETE FROM boxes WHERE id=?", (box_id,))
        log(db, "box-removed", f"box={box_id}")
    assign_waiting()


def malformed_boxes():
    return [b for b in boxes() if not clean_url(b["url"])]


# ---------------------------------------------------------------- registration

def _row_to_dict(row):
    return dict(row) if row is not None else None


def by_email(email):
    db = connect()
    try:
        return _row_to_dict(db.execute(
            "SELECT p.*, b.url AS box_url FROM participants p LEFT JOIN boxes b ON b.id = p.box_id"
            " WHERE p.email = ?", (normalise(email),)).fetchone())
    finally:
        db.close()


def by_token(token):
    if not token:
        return None
    db = connect()
    try:
        return _row_to_dict(db.execute(
            "SELECT p.*, b.url AS box_url FROM participants p LEFT JOIN boxes b ON b.id = p.box_id"
            " WHERE p.token = ?", (token,)).fetchone())
    finally:
        db.close()


def register(name, email, ip=""):
    """Idempotent by email: the same person gets the same instance back, however many times they
    submit the form or reopen the page. Returns (participant, created)."""
    email = normalise(email)
    with writing() as db:
        existing = db.execute(
            "SELECT id, state, box_id FROM participants WHERE email = ?", (email,)).fetchone()
        if existing and existing["state"] == "released":
            # They left and came back. Make them active again and give them an instance if one is
            # free, rather than leaving them with the row of a person who has gone.
            db.execute("UPDATE participants SET state='active' WHERE id=?", (existing["id"],))
            box = db.execute(
                "SELECT id FROM boxes WHERE state = 'free' ORDER BY id LIMIT 1").fetchone()
            if box:
                db.execute("UPDATE participants SET box_id=? WHERE id=?",
                           (box["id"], existing["id"]))
                db.execute("UPDATE boxes SET state='assigned', participant_id=?, assigned_at=?"
                           " WHERE id=?", (existing["id"], time.time(), box["id"]))
            log(db, "re-registered", email)
        if existing:
            row = db.execute(
                "SELECT p.*, b.url AS box_url FROM participants p"
                " LEFT JOIN boxes b ON b.id = p.box_id WHERE p.id = ?", (existing["id"],)).fetchone()
            return _row_to_dict(row), False

        total = db.execute("SELECT COUNT(*) AS n FROM participants").fetchone()["n"]
        if total >= settings.account_cap:
            raise RegistrationClosed(f"the cap of {settings.account_cap} registrations is reached")

        token = secrets.token_urlsafe(24)
        box = db.execute("SELECT id FROM boxes WHERE state = 'free' ORDER BY id LIMIT 1").fetchone()
        cursor = db.execute(
            "INSERT INTO participants (name, email, token, box_id, created_at, ip)"
            " VALUES (?,?,?,?,?,?)",
            ((name or "").strip(), email, token, box["id"] if box else None, time.time(), ip))
        participant_id = cursor.lastrowid
        if box:
            db.execute(
                "UPDATE boxes SET state='assigned', participant_id=?, assigned_at=? WHERE id=?",
                (participant_id, time.time(), box["id"]))
        log(db, "registered", f"{email} box={box['id'] if box else 'none'}")
        row = db.execute(
            "SELECT p.*, b.url AS box_url FROM participants p LEFT JOIN boxes b ON b.id = p.box_id"
            " WHERE p.id = ?", (participant_id,)).fetchone()
        return _row_to_dict(row), True


def assign_waiting():
    """Hand newly uploaded instances to whoever registered before they existed, oldest first."""
    handed = 0
    with writing() as db:
        waiting = db.execute(
            "SELECT id FROM participants WHERE box_id IS NULL AND state='active'"
            " ORDER BY created_at").fetchall()
        for person in waiting:
            box = db.execute(
                "SELECT id FROM boxes WHERE state='free' ORDER BY id LIMIT 1").fetchone()
            if not box:
                break
            db.execute("UPDATE participants SET box_id=? WHERE id=?", (box["id"], person["id"]))
            db.execute(
                "UPDATE boxes SET state='assigned', participant_id=?, assigned_at=? WHERE id=?",
                (person["id"], time.time(), box["id"]))
            handed += 1
        if handed:
            log(db, "boxes-assigned", f"{handed} waiting participants served")
    return handed


# ---------------------------------------------------------------- galileo worker support

def next_queued():
    """Claim one queued participant for the worker, inside a write transaction so two workers
    cannot pick up the same row."""
    with writing() as db:
        row = db.execute(
            "SELECT * FROM participants WHERE galileo_state='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE participants SET galileo_state='creating', attempts=attempts+1 WHERE id=?",
            (row["id"],))
        return _row_to_dict(row)


def queue_position(participant_id):
    """How many people are ahead of them, so the page can say something true instead of spinning.
    Accounts are created one at a time to stay inside Galileo's rate limiter, so the queue is real
    and a hundred-person room drains over several minutes."""
    db = connect()
    try:
        row = db.execute("SELECT created_at, galileo_state FROM participants WHERE id=?",
                         (participant_id,)).fetchone()
        if not row or row["galileo_state"] not in ("queued", "creating"):
            return 0
        return db.execute(
            "SELECT COUNT(*) AS n FROM participants WHERE galileo_state IN ('queued','creating')"
            " AND created_at < ?", (row["created_at"],)).fetchone()["n"]
    finally:
        db.close()


def waiting_since(cutoff):
    """The oldest participant still waiting for an account from before cutoff, if any."""
    db = connect()
    try:
        return _row_to_dict(db.execute(
            "SELECT * FROM participants WHERE galileo_state IN ('queued','creating')"
            " AND created_at < ? ORDER BY created_at LIMIT 1", (cutoff,)).fetchone())
    finally:
        db.close()


def created_count():
    db = connect()
    try:
        placeholders = ",".join("?" * len(ACTIVE_GALILEO))
        return db.execute(
            f"SELECT COUNT(*) AS n FROM participants WHERE galileo_state IN ({placeholders})",
            ACTIVE_GALILEO).fetchone()["n"]
    finally:
        db.close()


def set_galileo(participant_id, state, email="", error="", password=None):
    """password is the one the account was created with, kept per participant so that changing
    the default on the admin page never shows someone a password their account does not have."""
    with writing() as db:
        db.execute(
            "UPDATE participants SET galileo_state=?, galileo_email=?, galileo_error=? WHERE id=?",
            (state, email, error[:500], participant_id))
        if password is not None:
            db.execute("UPDATE participants SET galileo_password=? WHERE id=?",
                       (password, participant_id))
        log(db, f"galileo-{state}", f"participant={participant_id} {error[:200]}")


def requeue(participant_id, error=""):
    with writing() as db:
        db.execute(
            "UPDATE participants SET galileo_state='queued', galileo_error=? WHERE id=?",
            (error[:500], participant_id))


def issue_pool_account(participant_id, note=""):
    """Last resort when the Galileo API will not play: hand out one of the pre-made accounts.
    note says why, for the roster."""
    with writing() as db:
        row = db.execute("SELECT * FROM pool WHERE state='free' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        db.execute("UPDATE pool SET state='issued', participant_id=? WHERE id=?",
                   (participant_id, row["id"]))
        # Fallback accounts were made ahead of time with the installer's password, whatever the
        # admin page has set since.
        db.execute(
            "UPDATE participants SET galileo_state='pool', galileo_email=?, galileo_error=?,"
            " galileo_password=? WHERE id=?",
            (row["email"], note[:500], settings.galileo_password, participant_id))
        log(db, "galileo-pool", f"participant={participant_id} {row['email']}")
        return row["email"]


# ---------------------------------------------------------------- progress

STEPS = range(1, 9)


def mark_step(participant_id, step, source):
    """Record the first time a step was seen done. Later sightings change nothing, so the time is
    when they got there, which is what working out who is stuck needs."""
    with writing() as db:
        db.execute("INSERT OR IGNORE INTO progress (participant_id, step, source, at)"
                   " VALUES (?,?,?,?)", (participant_id, step, source, time.time()))


def unmark_step(participant_id, step, source="self"):
    with writing() as db:
        db.execute("DELETE FROM progress WHERE participant_id=? AND step=? AND source=?",
                   (participant_id, step, source))


def steps_for(participant_id, source=None):
    db = connect()
    try:
        sql = "SELECT step, source, at FROM progress WHERE participant_id=?"
        args = [participant_id]
        if source:
            sql += " AND source=?"
            args.append(source)
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def record_probe(box_id, reachable, note="", partial=()):
    with writing() as db:
        db.execute("INSERT INTO probes (box_id, checked_at, reachable, note, partial)"
                   " VALUES (?,?,?,?,?) ON CONFLICT(box_id) DO UPDATE SET"
                   " checked_at=excluded.checked_at, reachable=excluded.reachable,"
                   " note=excluded.note, partial=excluded.partial",
                   (box_id, time.time(), 1 if reachable else 0, note[:200],
                    ",".join(str(s) for s in sorted(partial))))


def assigned_boxes():
    """Instances someone is using, with who: what the tracker visits."""
    db = connect()
    try:
        return [dict(r) for r in db.execute(
            "SELECT b.id, b.url, p.id AS participant_id FROM boxes b"
            " JOIN participants p ON p.box_id = b.id"
            " WHERE b.state='assigned' AND p.state='active'").fetchall()]
    finally:
        db.close()


def progress_board(stuck_after=600, now=None):
    """One row per active participant: each step done automatically, by their own tick, under way,
    or not yet; the step they are on and for how long; and what the last look at their instance
    found. A row is stuck when the step they are on has outlasted stuck_after seconds."""
    now = now or time.time()
    db = connect()
    try:
        people = [dict(r) for r in db.execute(
            "SELECT p.id, p.name, p.email, p.created_at, b.url AS box_url, b.id AS box_id,"
            " pr.checked_at, pr.reachable, pr.note, pr.partial"
            " FROM participants p LEFT JOIN boxes b ON b.id = p.box_id"
            " LEFT JOIN probes pr ON pr.box_id = b.id"
            " WHERE p.state='active' ORDER BY p.created_at").fetchall()]
        marks = {}
        for r in db.execute("SELECT participant_id, step, source, at FROM progress"):
            marks.setdefault(r["participant_id"], {}).setdefault(r["step"], {})[r["source"]] = r["at"]
    finally:
        db.close()

    rows = []
    for person in people:
        seen = marks.get(person["id"], {})
        partial = {int(s) for s in (person["partial"] or "").split(",") if s}
        finished_at = {step: min(sources.values()) for step, sources in seen.items() if sources}
        # Where someone is, is one past the furthest step reached. Not the first gap: steps 4 to 6
        # only count when ticked, so the first gap would leave anyone who skips a tick looking
        # stuck on a step they finished long ago.
        furthest = max(finished_at) if finished_at else 0
        cells = []
        for step in STEPS:
            sources = seen.get(step, {})
            if "auto" in sources:
                state = "auto"
            elif "self" in sources:
                state = "self"
            elif step in partial:
                state = "partial"
            elif step < furthest:
                state = "implied"  # not seen, but a later step was
            else:
                state = "none"
            cells.append({"step": step, "state": state})
        current = furthest + 1 if furthest < max(STEPS) else None
        since = (finished_at[furthest] if furthest else person["created_at"]) if current else None
        minutes = int((now - since) // 60) if since else 0
        rows.append({
            **person,
            "box_url": clean_url(person["box_url"]),
            "cells": cells,
            "current": current,
            "minutes": minutes,
            "stuck": current is not None and since is not None and now - since > stuck_after,
            "done": len(finished_at),
        })
    return rows


# ---------------------------------------------------------------- admin views

def counts():
    db = connect()
    try:
        def one(sql, args=()):
            return db.execute(sql, args).fetchone()["n"]
        states = {r["galileo_state"]: r["n"] for r in db.execute(
            "SELECT galileo_state, COUNT(*) AS n FROM participants GROUP BY galileo_state")}
        return {
            "boxes_total": one("SELECT COUNT(*) AS n FROM boxes"),
            "boxes_free": one("SELECT COUNT(*) AS n FROM boxes WHERE state='free'"),
            "boxes_assigned": one("SELECT COUNT(*) AS n FROM boxes WHERE state='assigned'"),
            "participants": one("SELECT COUNT(*) AS n FROM participants"),
            "waiting": one("SELECT COUNT(*) AS n FROM participants"
                           " WHERE box_id IS NULL AND state='active'"),
            "pool_free": one("SELECT COUNT(*) AS n FROM pool WHERE state='free'"),
            "pool_total": one("SELECT COUNT(*) AS n FROM pool"),
            "galileo": states,
            "cap": settings.account_cap,
        }
    finally:
        db.close()


def roster():
    db = connect()
    try:
        return [dict(r) for r in db.execute(
            "SELECT p.*, b.url AS box_url, b.label AS box_label FROM participants p"
            " LEFT JOIN boxes b ON b.id = p.box_id ORDER BY p.created_at").fetchall()]
    finally:
        db.close()


def boxes():
    db = connect()
    try:
        return [dict(r) for r in db.execute(
            "SELECT b.*, p.email AS participant_email FROM boxes b"
            " LEFT JOIN participants p ON p.id = b.participant_id ORDER BY b.id").fetchall()]
    finally:
        db.close()


def recent_events(limit=50):
    db = connect()
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        db.close()


def release(participant_id):
    """Free the instance for somebody else. The person is marked released rather than deleted, so
    the roster still shows they were here, and so the instance they vacate goes to whoever is
    waiting rather than straight back to them."""
    with writing() as db:
        db.execute("UPDATE boxes SET state='free', participant_id=NULL, assigned_at=NULL"
                   " WHERE participant_id=?", (participant_id,))
        db.execute("UPDATE participants SET box_id=NULL, state='released' WHERE id=?",
                   (participant_id,))
        log(db, "box-released", f"participant={participant_id}")
    assign_waiting()


def retry(participant_id):
    with writing() as db:
        db.execute("UPDATE participants SET galileo_state='queued', galileo_error='', attempts=0"
                   " WHERE id=? AND galileo_state IN ('failed','pool')", (participant_id,))
        log(db, "galileo-retry", f"participant={participant_id}")


def export_csv():
    fields = ["name", "email", "box_url", "galileo_email", "galileo_state", "registered_at"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in roster():
        writer.writerow({
            "name": row["name"],
            "email": row["email"],
            "box_url": clean_url(row["box_url"]),
            "galileo_email": row["galileo_email"],
            "galileo_state": row["galileo_state"],
            "registered_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["created_at"])),
        })
    return out.getvalue()
