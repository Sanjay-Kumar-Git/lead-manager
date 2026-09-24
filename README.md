# Admission Lead Manager

FastAPI + SQLite (stdlib) + one-file vanilla JS UI. No build step.

## Run
```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload        # open http://127.0.0.1:8000
pytest -q                            # run tests
```
API docs: http://127.0.0.1:8000/docs

## Structure
```
lead-manager/
├── README.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py            # schema, business rules, REST API
│   └── static/index.html  # dashboard + leads UI
└── tests/test_api.py
```

## Approach & assumptions
- Users: counsellors and admission managers (no login in the prototype; auth would be the next step).
- Every lead gets a counsellor automatically (least open leads), can be reassigned manually, and starts with a "First contact" follow-up due today.
- Funnel: New -> Contacted -> Interested -> Application Started -> Enrolled; Lost from any open stage (reason mandatory); Lost can be reopened to Contacted.
- Phone number (last 10 digits) is the identity: duplicates from another channel are rejected with a pointer to the existing lead.
- Closed leads auto-complete their pending follow-ups so they never show as overdue.
- Ageing = days since creation, bucketed for open leads only.
- Manager dashboard: funnel, source conversion, course demand, counsellor load, ageing, lost reasons, overdue follow-ups.

## Trade-offs / not done
- SQLite and no auth/roles; no real WhatsApp/website integrations (leads are entered via form/API, `POST /api/leads` is the hook for them).
- Least-loaded assignment ignores course specialisation and working hours.
- Age is measured from creation, not last activity.

## Edge cases covered
Duplicate phone in different formats, invalid phone/email/source/course, illegal status jumps, Lost without reason, follow-ups on closed leads, idempotent follow-up completion, unknown counsellor, empty dashboard (no divide-by-zero).
