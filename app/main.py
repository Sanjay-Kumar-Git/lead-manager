"""Admission Lead Management - FastAPI + SQLite (stdlib sqlite3, no ORM)."""
import os, re, sqlite3
from contextlib import contextmanager
from datetime import datetime, date
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "leads.db")
SOURCES = ["Website", "Walk-in", "Phone", "WhatsApp", "Education Fair", "Campaign", "Referral", "Other"]
COURSES = ["B.Tech CSE", "B.Tech ECE", "MBA", "BBA", "B.Com", "M.Tech"]
STATUSES = ["New", "Contacted", "Interested", "Application Started", "Enrolled", "Lost"]
CLOSED = ("Enrolled", "Lost")
# Allowed moves keep the funnel honest (no jumping New -> Enrolled).
TRANSITIONS = {
    "New": ["Contacted", "Lost"],
    "Contacted": ["Interested", "Lost"],
    "Interested": ["Application Started", "Lost"],
    "Application Started": ["Enrolled", "Lost"],
    "Enrolled": [],
    "Lost": ["Contacted"],  # reopen a lost lead
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS counsellors(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE, email TEXT,
  source TEXT NOT NULL, course TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'New',
  counsellor_id INTEGER REFERENCES counsellors(id), lost_reason TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS followups(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
  due_date TEXT NOT NULL, note TEXT, done INTEGER NOT NULL DEFAULT 0, done_at TEXT);
CREATE TABLE IF NOT EXISTS activities(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
  text TEXT NOT NULL, created_at TEXT NOT NULL);
"""


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now():
    return datetime.now().isoformat(timespec="seconds")


def init():
    with db() as c:
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM counsellors").fetchone():
            c.executemany("INSERT INTO counsellors(name) VALUES(?)",
                          [("Asha Rao",), ("Vikram Shah",), ("Meera Nair",)])


def log(c, lead_id, text):
    c.execute("INSERT INTO activities(lead_id,text,created_at) VALUES(?,?,?)", (lead_id, text, now()))


def pick_counsellor(c):
    """Least-loaded assignment: counsellor with fewest open leads (ties -> lowest id)."""
    row = c.execute("""SELECT co.id FROM counsellors co
        LEFT JOIN leads l ON l.counsellor_id=co.id AND l.status NOT IN ('Enrolled','Lost')
        GROUP BY co.id ORDER BY COUNT(l.id), co.id LIMIT 1""").fetchone()
    return row["id"]


def norm_phone(p):
    d = re.sub(r"\D", "", p or "")[-10:]  # drop +91 / spaces / dashes
    if len(d) != 10:
        raise HTTPException(422, "Phone must contain 10 digits")
    return d


app = FastAPI(title="Admission Lead Manager")
init()


class LeadIn(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    source: str
    course: str
    counsellor_id: Optional[int] = None


class StatusIn(BaseModel):
    status: str
    lost_reason: Optional[str] = None


class AssignIn(BaseModel):
    counsellor_id: int


class FollowupIn(BaseModel):
    due_date: str  # YYYY-MM-DD
    note: Optional[str] = ""


def lead_row(r):
    d = dict(r)
    d["age_days"] = (date.today() - datetime.fromisoformat(d["created_at"]).date()).days
    return d


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/meta")
def meta():
    with db() as c:
        cs = [dict(r) for r in c.execute("SELECT * FROM counsellors")]
    return {"sources": SOURCES, "courses": COURSES, "statuses": STATUSES,
            "transitions": TRANSITIONS, "counsellors": cs}


@app.post("/api/leads", status_code=201)
def create_lead(b: LeadIn):
    if not b.name.strip():
        raise HTTPException(422, "Name is required")
    if b.source not in SOURCES:
        raise HTTPException(422, "Unknown source")
    if b.course not in COURSES:
        raise HTTPException(422, "Unknown course")
    if b.email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", b.email):
        raise HTTPException(422, "Invalid email")
    phone = norm_phone(b.phone)
    with db() as c:
        dup = c.execute("SELECT id,name FROM leads WHERE phone=?", (phone,)).fetchone()
        if dup:  # same person via another channel: don't create a second lead
            raise HTTPException(409, f"Duplicate: lead #{dup['id']} ({dup['name']}) already has this phone")
        if b.counsellor_id and not c.execute("SELECT 1 FROM counsellors WHERE id=?", (b.counsellor_id,)).fetchone():
            raise HTTPException(422, "Unknown counsellor")
        cid = b.counsellor_id or pick_counsellor(c)
        t = now()
        cur = c.execute("""INSERT INTO leads(name,phone,email,source,course,counsellor_id,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (b.name.strip(), phone, b.email, b.source, b.course, cid, t, t))
        lid = cur.lastrowid
        who = c.execute("SELECT name FROM counsellors WHERE id=?", (cid,)).fetchone()["name"]
        log(c, lid, f"Lead created via {b.source}; assigned to {who}")
        # every new lead gets a first-contact follow-up due today
        c.execute("INSERT INTO followups(lead_id,due_date,note) VALUES(?,?,?)",
                  (lid, date.today().isoformat(), "First contact"))
    return {"id": lid}


@app.get("/api/leads")
def list_leads(status: str = "", source: str = "", counsellor_id: int = 0, q: str = ""):
    sql = """SELECT l.*, co.name AS counsellor,
      (SELECT MIN(due_date) FROM followups f WHERE f.lead_id=l.id AND f.done=0) AS next_followup
      FROM leads l LEFT JOIN counsellors co ON co.id=l.counsellor_id WHERE 1=1"""
    a = []
    if status:
        sql += " AND l.status=?"; a.append(status)
    if source:
        sql += " AND l.source=?"; a.append(source)
    if counsellor_id:
        sql += " AND l.counsellor_id=?"; a.append(counsellor_id)
    if q:
        sql += " AND (l.name LIKE ? OR l.phone LIKE ?)"; a += [f"%{q}%", f"%{q}%"]
    with db() as c:
        rows = [lead_row(r) for r in c.execute(sql + " ORDER BY l.created_at DESC", a)]
    today = date.today().isoformat()
    for r in rows:
        r["overdue"] = bool(r["next_followup"] and r["next_followup"] < today and r["status"] not in CLOSED)
    return rows


@app.get("/api/leads/{lid}")
def get_lead(lid: int):
    with db() as c:
        r = c.execute("""SELECT l.*, co.name AS counsellor FROM leads l
                         LEFT JOIN counsellors co ON co.id=l.counsellor_id WHERE l.id=?""", (lid,)).fetchone()
        if not r:
            raise HTTPException(404, "Lead not found")
        return {**lead_row(r),
                "followups": [dict(x) for x in c.execute("SELECT * FROM followups WHERE lead_id=? ORDER BY due_date", (lid,))],
                "activities": [dict(x) for x in c.execute("SELECT * FROM activities WHERE lead_id=? ORDER BY id DESC", (lid,))]}


@app.post("/api/leads/{lid}/status")
def set_status(lid: int, b: StatusIn):
    with db() as c:
        r = c.execute("SELECT status FROM leads WHERE id=?", (lid,)).fetchone()
        if not r:
            raise HTTPException(404, "Lead not found")
        if b.status not in TRANSITIONS.get(r["status"], []):
            raise HTTPException(422, f"Cannot move from {r['status']} to {b.status}")
        if b.status == "Lost" and not (b.lost_reason or "").strip():
            raise HTTPException(422, "A reason is required when marking a lead Lost")
        c.execute("UPDATE leads SET status=?, lost_reason=?, updated_at=? WHERE id=?",
                  (b.status, b.lost_reason if b.status == "Lost" else None, now(), lid))
        if b.status in CLOSED:  # closed leads shouldn't keep nagging counsellors
            c.execute("UPDATE followups SET done=1, done_at=? WHERE lead_id=? AND done=0", (now(), lid))
        log(c, lid, f"Status: {r['status']} -> {b.status}" + (f" ({b.lost_reason})" if b.status == "Lost" else ""))
    return {"ok": True}


@app.post("/api/leads/{lid}/assign")
def assign(lid: int, b: AssignIn):
    with db() as c:
        if not c.execute("SELECT 1 FROM leads WHERE id=?", (lid,)).fetchone():
            raise HTTPException(404, "Lead not found")
        co = c.execute("SELECT name FROM counsellors WHERE id=?", (b.counsellor_id,)).fetchone()
        if not co:
            raise HTTPException(422, "Unknown counsellor")
        c.execute("UPDATE leads SET counsellor_id=?, updated_at=? WHERE id=?", (b.counsellor_id, now(), lid))
        log(c, lid, f"Reassigned to {co['name']}")
    return {"ok": True}


@app.post("/api/leads/{lid}/followups", status_code=201)
def add_followup(lid: int, b: FollowupIn):
    try:
        d = date.fromisoformat(b.due_date)
    except ValueError:
        raise HTTPException(422, "due_date must be YYYY-MM-DD")
    with db() as c:
        r = c.execute("SELECT status FROM leads WHERE id=?", (lid,)).fetchone()
        if not r:
            raise HTTPException(404, "Lead not found")
        if r["status"] in CLOSED:
            raise HTTPException(422, "Lead is closed; reopen it before scheduling follow-ups")
        c.execute("INSERT INTO followups(lead_id,due_date,note) VALUES(?,?,?)", (lid, d.isoformat(), b.note))
        log(c, lid, f"Follow-up scheduled for {d.isoformat()}: {b.note}")
    return {"ok": True}


@app.post("/api/followups/{fid}/done")
def done_followup(fid: int):
    with db() as c:
        f = c.execute("SELECT * FROM followups WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "Follow-up not found")
        if f["done"]:
            return {"ok": True}  # idempotent
        c.execute("UPDATE followups SET done=1, done_at=? WHERE id=?", (now(), fid))
        log(c, f["lead_id"], f"Follow-up completed ({f['note']})")
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard():
    today = date.today().isoformat()
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]
        by_status = {s: 0 for s in STATUSES}
        for r in c.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status"):
            by_status[r["status"]] = r["n"]
        by_source = [{"source": r["source"], "leads": r["n"], "enrolled": r["e"],
                      "conversion_pct": round(100 * r["e"] / r["n"], 1)}
                     for r in c.execute("SELECT source, COUNT(*) n, SUM(status='Enrolled') e FROM leads GROUP BY source ORDER BY n DESC")]
        by_course = [dict(r) for r in c.execute("SELECT course, COUNT(*) leads FROM leads GROUP BY course ORDER BY leads DESC")]
        by_counsellor = [dict(r) for r in c.execute("""SELECT co.name, COUNT(l.id) total,
            COALESCE(SUM(l.status NOT IN ('Enrolled','Lost')),0) open, COALESCE(SUM(l.status='Enrolled'),0) enrolled
            FROM counsellors co LEFT JOIN leads l ON l.counsellor_id=co.id GROUP BY co.id""")]
        overdue = [dict(r) for r in c.execute("""SELECT f.id, f.due_date, f.note, l.id lead_id, l.name, co.name counsellor
            FROM followups f JOIN leads l ON l.id=f.lead_id LEFT JOIN counsellors co ON co.id=l.counsellor_id
            WHERE f.done=0 AND f.due_date<? ORDER BY f.due_date""", (today,))]
        ageing = {"0-2 days": 0, "3-7 days": 0, "8+ days": 0}
        for r in c.execute("SELECT created_at FROM leads WHERE status NOT IN ('Enrolled','Lost')"):
            a = (date.today() - datetime.fromisoformat(r["created_at"]).date()).days
            ageing["0-2 days" if a <= 2 else "3-7 days" if a <= 7 else "8+ days"] += 1
        lost = [dict(r) for r in c.execute("SELECT lost_reason reason, COUNT(*) n FROM leads WHERE status='Lost' GROUP BY lost_reason ORDER BY n DESC")]
    return {"total": total, "by_status": by_status, "by_source": by_source, "by_course": by_course,
            "by_counsellor": by_counsellor, "overdue_followups": overdue, "open_lead_ageing": ageing,
            "lost_reasons": lost,
            "conversion_pct": round(100 * by_status["Enrolled"] / total, 1) if total else 0}


def seed_demo():
    """Optional demo data for a live deployment (only when SEED_DEMO=1 and DB is empty)."""
    with db() as c:
        if c.execute("SELECT 1 FROM leads").fetchone():
            return
    people = [("Ravi Kumar", "MBA", "Walk-in"), ("Priya Sharma", "B.Tech CSE", "Website"),
              ("Arjun Mehta", "BBA", "WhatsApp"), ("Sneha Iyer", "B.Com", "Education Fair"),
              ("Karan Patel", "B.Tech ECE", "Campaign"), ("Divya Reddy", "M.Tech", "Phone"),
              ("Imran Khan", "MBA", "Referral"), ("Anita Das", "B.Tech CSE", "Website")]
    ids = [create_lead(LeadIn(name=n, phone=f"98{i:02d}5501{i:02d}", source=s, course=co))["id"]
           for i, (n, co, s) in enumerate(people, 1)]
    for i, path in [(0, ["Contacted", "Interested", "Application Started", "Enrolled"]),
                    (1, ["Contacted", "Interested"]), (2, ["Contacted"]), (4, ["Contacted", "Interested", "Application Started", "Enrolled"])]:
        for st in path:
            set_status(ids[i], StatusIn(status=st))
    set_status(ids[5], StatusIn(status="Lost", lost_reason="Fees too high"))
    with db() as c:  # backdate a few leads so ageing and overdue follow-ups show up
        for lid, days in [(ids[2], 9), (ids[3], 5), (ids[6], 12)]:
            c.execute("UPDATE leads SET created_at=datetime('now','localtime',?) WHERE id=?", (f"-{days} days", lid))
            c.execute("UPDATE followups SET due_date=date('now','localtime',?) WHERE lead_id=? AND done=0", (f"-{days - 1} days", lid))


if os.environ.get("SEED_DEMO") == "1":
    seed_demo()
