import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)


def L(**k):
    return {"name": "A", "phone": "98450 12345", "source": "Website", "course": "MBA", **k}


def test_create_and_duplicate():
    assert c.post("/api/leads", json=L()).status_code == 201
    assert c.post("/api/leads", json=L(phone="+91-9845012345")).status_code == 409  # same number, other format


def test_validation():
    assert c.post("/api/leads", json=L(phone="123", name="B")).status_code == 422
    assert c.post("/api/leads", json=L(phone="9000000001", source="Fax")).status_code == 422


def test_spread_assignment():
    ids = [c.post("/api/leads", json=L(name=f"N{i}", phone=f"90000000{i:02d}")).json()["id"] for i in range(3)]
    assert len({c.get(f"/api/leads/{i}").json()["counsellor_id"] for i in ids}) >= 2


def test_status_rules():
    i = c.post("/api/leads", json=L(name="S", phone="9111111111")).json()["id"]
    assert c.post(f"/api/leads/{i}/status", json={"status": "Enrolled"}).status_code == 422  # skipping stages
    assert c.post(f"/api/leads/{i}/status", json={"status": "Lost"}).status_code == 422      # no reason
    assert c.post(f"/api/leads/{i}/status", json={"status": "Lost", "lost_reason": "Fees"}).status_code == 200
    assert c.post(f"/api/leads/{i}/followups", json={"due_date": "2030-01-01"}).status_code == 422  # closed
    assert c.post(f"/api/leads/{i}/status", json={"status": "Contacted"}).status_code == 200  # reopen


def test_dashboard():
    assert c.get("/api/dashboard").json()["total"] >= 1
