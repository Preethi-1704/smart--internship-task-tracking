# DefineInfoTech Internship Task Tracking & Automation System

Streamlit + SQLite internship operations application with role-scoped views, intern/team/task records, attendance, assessments, deadline monitoring, Excel templates/exports, PDF reports, audit logs, data-quality checks, and SQLite backup validation.

## Install and run
Python 3.11+ recommended.

**Windows PowerShell**
```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
# Edit .env: ADMIN_INITIAL_PASSWORD must be 12+ characters
python -m pytest -q
streamlit run app.py
```

**Linux/macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and set ADMIN_INITIAL_PASSWORD (12+ characters)
python -m pytest -q
streamlit run app.py
```

The database initializes on launch. The app opens directly to the dashboard without a login screen. On first run, synthetic sample records are initialized when the database is empty. Replace sample records with real records before operational use.

## Logo
The exact DefineInfoTech logo supplied by the user is included at `assets/dit_logo.png` and is displayed in the sidebar. The original image proportions are preserved.

## Key definitions
- Completion % = tasks assessed Passed / all assigned tasks × 100.
- Attendance % = Present / (Present + Absent) × 100. Leave and Holiday are excluded from denominator.
- Overdue: due date before today and task has not been submitted/reviewed. Due-today is separate; upcoming defaults to the next 3 calendar days.
- Team lead views are team-scoped; intern views are own-record scoped. Admin sees all.

## Excel and reports
Excel (`.xlsx`) and CSV (`.csv`) templates are provided in `templates/` for interns, teams, tasks, and attendance. Excel Import Center accepts CSV and XLSX files and imports intern, team, task, and attendance records into SQLite. It validates required columns, IDs, foreign keys, date order, statuses, and duplicates. Imports are atomic: if any row fails validation, no rows from that file are saved. Download the validation error CSV, correct the source file, and retry. Existing IDs are rejected rather than silently overwritten. Files are limited to 5 MB and dates must use `YYYY-MM-DD`. Intern register CSV export is also available from Intern Management. PDF reports are available under Reports & Exports.

## Backup, email and deployment
Backup & Settings creates an SQLite backup and checks `PRAGMA integrity_check`. Restoration is intentionally offline/documented rather than a one-click live overwrite. SMTP values are placeholders only; outbound email scheduling is not implemented, so the app never claims emails were sent. SQLite is appropriate for local demos/small teams; for concurrent multi-user production, migrate to PostgreSQL, add migrations, HTTPS, managed secrets and deployment monitoring.


## Direct dashboard access

The app opens directly to the dashboard without a login screen, as requested. Keep this local-use build on a trusted computer only; do not expose it to a public/shared network or use it with confidential real personal data.


## Automatic CSV workflow
Upload a completed supported CSV template in **Excel Import Center**. Validation and database import start automatically after upload; there is no separate import button. The same file is not processed twice in the same Streamlit session. Imports are atomic: if any row is invalid, nothing from that file is saved and a row-level error report is shown for download. CSV/XLSX upload is the trigger; the system cannot ingest a file that has not been supplied or placed in a configured watched folder.

## Task tracking and automation
The Dashboard and Task Tracking page show Low, Medium, and High task risk by intern and team. Risk is calculated from due date, task status, priority, and assessment result. Task Tracking separates individual intern work from team summaries. Attendance includes an automated reconciliation action that marks only missing attendance records as Absent while preserving existing records. Assessments support Passed, Need Revision, and Fail. Deadline Monitoring, Reports & Exports, and Data Quality use explicit empty-state handling to avoid displaying Streamlit internal objects. This risk rule is an operational heuristic, not an official company policy.
