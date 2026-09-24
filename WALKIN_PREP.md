# Walk-in Prep: explain your own project

## 30-second pitch
"Admission Lead Manager takes leads from any channel, auto-assigns a counsellor, forces follow-ups, enforces a proper funnel, and gives managers a dashboard of conversion, ageing and overdue work. It is FastAPI + SQLite with a one-file UI, so it runs with a single command."

## How it fits together
- `app/main.py` holds everything server-side: the database schema, business rules, and REST endpoints.
- `app/static/index.html` is the UI. It calls `/api/...` with `fetch` and renders three tabs: Dashboard, Leads, Add lead.
- SQLite via Python's built-in `sqlite3`: four tables: `counsellors`, `leads`, `followups`, `activities`.
- The tests call the API in-process with FastAPI's `TestClient` and a temporary database.

## The key decisions (be ready to justify each)
| Decision | Why | Downside |
|---|---|---|
| Phone (last 10 digits) is the identity, with a UNIQUE constraint | The same person often arrives via web, WhatsApp and a call; this prevents duplicates | Two people sharing a phone (e.g. parent's number) get blocked |
| Least-loaded auto-assignment | Fair and simple; nobody is overloaded | Ignores course expertise, shifts, leave |
| Restricted status transitions (`TRANSITIONS` dict) | Keeps funnel numbers trustworthy | Less flexible for odd real cases |
| Lost needs a reason | Gives managers "why we lose leads" insight | Slightly slower data entry |
| Closing a lead clears its open follow-ups | Prevents false "overdue" alerts | Reopening does not restore them |
| Every action logged to `activities` | Audit trail and history | Table grows over time |
| Ageing counts days since creation for open leads | Simple, easy to explain | Better measure would be days since last activity |
| No login | Time limit | Anyone can act as anyone; next step is roles |

## Likely questions and short answers
- **What if two leads arrive at the same time with the same number?** The UNIQUE constraint in the database rejects the second even if the app check races.
- **Why SQLite?** Zero setup for a prototype. For production I would move to PostgreSQL; the SQL is simple enough to port.
- **How would you add WhatsApp/website leads?** Those systems call `POST /api/leads`. I'd add an API key and a webhook endpoint.
- **How would you scale it?** Move to PostgreSQL, add indexes on `status`, `counsellor_id` and `due_date`, add pagination, and add authentication.
- **What would you add next?** Login with counsellor/manager roles, reminders by email/WhatsApp, course-based assignment, CSV import, and a "stale lead" alert based on last activity.
- **What did AI get wrong?** See AI_USAGE_REPORT.md: folder creation failed, empty `__init__.py`, Mac-only commands. I caught them from errors and fixed them.
- **Where does the overdue flag come from?** Earliest undone follow-up date is before today and the lead is not Enrolled/Lost. It is computed at read time, not stored.

## 3-minute demo script
1. **Dashboard (20s):** "This is the manager view: funnel, conversion by source, counsellor workload, ageing and overdue follow-ups."
2. **Add lead (30s):** Add "Ravi Kumar", phone 9876543210, Walk-in, MBA. Point out the auto-assigned counsellor and the "First contact" follow-up.
3. **Duplicate (20s):** Add the same phone as `+91 98765 43210`. Show the duplicate error naming the existing lead.
4. **Funnel rules (40s):** Open Ravi. Show only valid next statuses. Move to Contacted, then Interested. Try Lost with no reason and show the error. Then mark Lost with a reason.
5. **Follow-ups and history (30s):** Schedule a follow-up for a past date on another lead to show it turn red. Show the activity log.
6. **Back to dashboard (20s):** Numbers and lost reasons have updated.
7. **Close (20s):** "Limits: no login, simple assignment. Next I'd add roles and WhatsApp integration."

Tip: add a few sample leads before you start so the dashboard is not empty. To reset, stop the server and delete `leads.db`.
