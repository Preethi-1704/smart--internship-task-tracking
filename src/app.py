import os
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from datetime import date
from io import BytesIO
from config.settings import LOGO
from database.connection import init_db, connect
from services.core import (
    authenticate, hash_password, seed, tasks, deadlines, save_intern,
    save_task, audit, backup, allowed, verify_password, reset_workspace
)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(
    page_title="Internship Task Tracking Automation",
    layout="wide",
    page_icon="📘"
)
init_db()

with connect() as c:
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        pw = os.getenv("ADMIN_INITIAL_PASSWORD", "")
        if len(pw) >= 12:
            c.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                (os.getenv("ADMIN_USERNAME", "admin"), hash_password(pw), "admin")
            )

if "user" not in st.session_state:
    st.session_state.user = {
        "username": "demo_admin", "role": "admin",
        "intern_id": None, "team_id": None
    }


def risk_level(r):
    from datetime import timedelta
    today = date.today().isoformat()
    status = str(r.get("status", ""))
    assessment = str(r.get("assessment_status", ""))
    due = str(r.get("due_date", ""))
    priority = str(r.get("priority", ""))
    if assessment == "Passed":
        return "Low"
    if (
        (due and due < today and status not in ("Submitted", "Reviewed"))
        or priority in ("High", "Critical")
        or assessment in ("Need Revision", "Needs Revision", "Fail")
    ):
        return "High"
    if priority == "Medium" or (
        due and due <= (date.today() + timedelta(days=3)).isoformat()
        and status not in ("Submitted", "Reviewed")
    ):
        return "Medium"
    return "Low"


def main(user):
    with st.sidebar:
        if LOGO.exists():
            st.image(str(LOGO), width=200)
        st.markdown("### Internship Automation")
        pages = [
            "Dashboard", "Intern Management", "Team Management",
            "Task Management", "Task Tracking", "Attendance", "Assessments",
            "Deadline Monitoring", "Reports & Exports", "Excel Import Center",
            "Data Quality", "Audit Logs", "User Management",
            "Backup & Settings", "User Guide", "Change Password"
        ]
        if user["role"] != "admin":
            pages = [
                x for x in pages if x not in [
                    "Team Management", "Excel Import Center", "Audit Logs",
                    "User Management", "Backup & Settings"
                ]
            ]
        page = st.radio("Navigation", pages)

        # Demo data is initialized only when explicitly requested. This prevents
        # the deleted records from being recreated automatically after a reset.
        with connect() as c:
            intern_count = c.execute("SELECT COUNT(*) FROM interns").fetchone()[0]
        if user["role"] == "admin" and intern_count == 0:
            if st.button("Initialize demo workspace", key="initialize_demo_workspace"):
                try:
                    seed()
                    st.success("Demo workspace initialized.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Demo initialization failed: {e}")

        # Reset means clear workspace data, not merely rerun the page.
        if user["role"] == "admin":
            if st.button("Reset dashboard session", key="reset_dashboard_session"):
                st.session_state["confirm_workspace_reset"] = True
        else:
            st.button("Reset dashboard session", disabled=True,
                      help="Only an administrator can reset workspace data.")

    if st.session_state.get("confirm_workspace_reset", False):
        st.warning(
            "Permanent action: this deletes workspace records such as interns, "
            "teams, tasks, attendance, reviews, and audit logs. Admin user "
            "accounts are preserved. A database backup will be attempted first."
        )
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm: Delete All Workspace Data", type="primary",
                         key="confirm_delete_workspace"):
                try:
                    backup_path = backup()
                    reset_workspace()
                    st.session_state.clear()
                    st.session_state["reset_complete"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Reset failed. No success was reported. Details: {e}")
        with cancel_col:
            if st.button("Cancel Reset", key="cancel_delete_workspace"):
                st.session_state.pop("confirm_workspace_reset", None)
                st.rerun()

    if st.session_state.pop("reset_complete", False):
        st.success("Workspace data reset completed. Admin account(s) were preserved.")

    st.title(page)

    if page == "Dashboard":
        ts = tasks(user)
        ds = deadlines(user)
        with connect() as c:
            if user["role"] == "admin":
                ni = c.execute("SELECT COUNT(*) FROM interns WHERE active=1").fetchone()[0]
                nt = c.execute("SELECT COUNT(*) FROM teams WHERE active=1").fetchone()[0]
            elif user["role"] == "team_lead":
                ni = c.execute(
                    "SELECT COUNT(*) FROM interns WHERE active=1 AND team_id=?",
                    (user["team_id"],)
                ).fetchone()[0]
                nt = 1
            else:
                ni, nt = 1, 0
        passed = sum(t["assessment_status"] == "Passed" for t in ts)
        vals = [
            ("Active interns", ni), ("Teams", nt), ("Assigned tasks", len(ts)),
            ("Not started", sum(t["status"] == "Not Started" for t in ts)),
            ("In progress", sum(t["status"] == "In Progress" for t in ts)),
            ("Awaiting review", len(ds["review_pending"])),
            ("Overdue", len(ds["overdue"])), ("Passed", passed),
            ("Needs revision", len(ds["revision"])),
            ("Completion %", round(passed / len(ts) * 100, 1) if ts else 0)
        ]
        cols = st.columns(5)
        for i, (k, v) in enumerate(vals):
            cols[i % 5].metric(k, v if k != "Completion %" else f"{v}%")
        if ts:
            df = pd.DataFrame(ts)
            a, b = st.columns(2)
            a.plotly_chart(
                px.pie(df, names="status", title="Task Status Distribution"),
                use_container_width=True
            )
            q = df.groupby("team_id").agg(
                total=("task_id", "count"),
                passed=("assessment_status", lambda s: (s == "Passed").sum())
            ).reset_index()
            q["completion %"] = (q.passed / q.total * 100).round(1)
            b.plotly_chart(
                px.bar(q, x="team_id", y="completion %",
                       title="Team-wise Successful Assessment %", range_y=[0, 100]),
                use_container_width=True
            )
            df["Risk Level"] = df.apply(risk_level, axis=1)
            risk = df.groupby(["full_name", "Risk Level"]).size().reset_index(name="Task Count")
            st.plotly_chart(
                px.bar(
                    risk, x="full_name", y="Task Count", color="Risk Level",
                    barmode="stack",
                    category_orders={"Risk Level": ["Low", "Medium", "High"]},
                    title="Intern-wise Work Risk (automatically calculated)",
                    labels={"full_name": "Intern", "Task Count": "Number of tasks"}
                ),
                use_container_width=True
            )
            st.caption(
                "Risk rule: High = overdue unfinished task, High/Critical priority, "
                "or Needs Revision; Medium = Medium priority or due within 3 days; "
                "Low = otherwise or successfully Passed. This is an operational "
                "heuristic, not an official DIT policy."
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif page == "Intern Management":
        if user["role"] == "admin":
            with connect() as c:
                teams = [dict(r) for r in c.execute("SELECT * FROM teams WHERE active=1")]
            if teams:
                with st.form("intern"):
                    a, b = st.columns(2)
                    iid = a.text_input("DIT Internship ID")
                    name = b.text_input("Full name")
                    email = a.text_input("Email")
                    phone = b.text_input("Contact number")
                    team = b.selectbox(
                        "Team", teams,
                        format_func=lambda t: f"{t['team_id']} — {t['team_name']}"
                    )
                    start = a.date_input("Start date")
                    end = b.date_input("End date")
                    ok = st.form_submit_button("Save intern")
                if ok:
                    try:
                        save_intern(
                            dict(
                                intern_id=iid, full_name=name, email=email, phone=phone,
                                team_id=team["team_id"], start_date=str(start),
                                end_date=str(end)
                            ),
                            user["username"]
                        )
                        st.success("Intern saved")
                    except Exception as e:
                        st.error(str(e))
        with connect() as c:
            q = "SELECT i.*,t.team_name FROM interns i JOIN teams t ON i.team_id=t.team_id"
            args = []
            if user["role"] == "team_lead":
                q += " WHERE i.team_id=?"
                args = [user["team_id"]]
            elif user["role"] == "intern":
                q += " WHERE i.intern_id=?"
                args = [user["intern_id"]]
            df = pd.read_sql_query(q, c, params=args)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            st.download_button("Export intern register", df.to_csv(index=False).encode(), "interns.csv")

    elif page == "Team Management":
        with connect() as c:
            df = pd.read_sql_query(
                "SELECT t.*,COUNT(i.intern_id) member_count FROM teams t "
                "LEFT JOIN interns i USING(team_id) GROUP BY t.team_id", c
            )
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.form("team"):
            tid = st.text_input("Team ID")
            tn = st.text_input("Team name")
            lead = st.text_input("Team lead username")
            ok = st.form_submit_button("Save team")
        if ok:
            if not tid or not tn:
                st.error("Team ID and name required")
            else:
                with connect() as c:
                    c.execute(
                        """INSERT INTO teams(team_id,team_name,lead_username)
                           VALUES(?,?,?) ON CONFLICT(team_id) DO UPDATE SET
                           team_name=excluded.team_name,lead_username=excluded.lead_username""",
                        (tid.upper(), tn, lead or None)
                    )
                audit(user["username"], "save_team", "team", tid)
                st.success("Team saved")
                st.rerun()

    elif page == "Task Management":
        if user["role"] == "admin":
            with connect() as c:
                interns = [dict(r) for r in c.execute(
                    "SELECT intern_id,team_id FROM interns WHERE active=1"
                )]
            if interns:
                with st.expander("Create / update task"):
                    with st.form("task"):
                        a, b = st.columns(2)
                        tid = a.text_input("Task ID")
                        title = b.text_input("Title")
                        intern = a.selectbox(
                            "Intern", interns, format_func=lambda x: x["intern_id"]
                        )
                        ass = a.date_input("Assigned date")
                        due = b.date_input("Due date")
                        status = a.selectbox(
                            "Status", ["Not Started", "In Progress", "Submitted", "Reviewed"]
                        )
                        assessment = b.selectbox(
                            "Assessment", ["Pending", "Passed", "Need Revision", "Fail"]
                        )
                        priority = a.selectbox("Priority", ["Low", "Medium", "High", "Critical"])
                        sub = b.date_input("Submission date (optional)", value=None)
                        comments = st.text_area("Reviewer comments")
                        ok = st.form_submit_button("Save task")
                    if ok:
                        try:
                            save_task(
                                dict(
                                    task_id=tid, title=title, intern_id=intern["intern_id"],
                                    team_id=intern["team_id"], assigned_date=str(ass),
                                    due_date=str(due), submission_date=str(sub) if sub else None,
                                    status=status, assessment_status=assessment,
                                    priority=priority, reviewer_comments=comments,
                                    reviewed_by=user["username"]
                                ),
                                user["username"]
                            )
                            st.success("Task saved")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
        df = pd.DataFrame(tasks(user))
        search = st.text_input("Search tasks")
        if not df.empty:
            if search:
                df = df[df.astype(str).apply(
                    lambda col: col.str.contains(search, case=False, na=False)
                ).any(axis=1)]
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif page == "Task Tracking":
        st.caption(
            "Live task tracking from the application database. "
            "Individual and team work are shown separately."
        )
        task_rows = tasks(user)
        tdf = pd.DataFrame(task_rows)
        if tdf.empty:
            st.info("No tasks available yet. Add tasks in Task Management or import a task register.")
        else:
            individual_tab, team_tab = st.tabs(["Individual Work", "Team Work"])
            with individual_tab:
                st.subheader("Individual intern work")
                people = sorted(tdf["full_name"].dropna().unique().tolist()) if "full_name" in tdf else []
                chosen = st.multiselect("Filter interns", people, default=people)
                idf = tdf[tdf["full_name"].isin(chosen)] if chosen and "full_name" in tdf else tdf.iloc[0:0]
                st.dataframe(idf, use_container_width=True, hide_index=True)
                if not idf.empty:
                    idf = idf.copy()
                    idf["Risk Level"] = idf.apply(risk_level, axis=1)
                    risk_counts = idf.groupby(["full_name", "Risk Level"]).size().reset_index(name="Task Count")
                    st.plotly_chart(
                        px.bar(
                            risk_counts, x="full_name", y="Task Count", color="Risk Level",
                            barmode="stack",
                            category_orders={"Risk Level": ["Low", "Medium", "High"]},
                            title="Individual Work — Risk by Intern"
                        ),
                        use_container_width=True
                    )
            with team_tab:
                st.subheader("Team-level work summary")
                team_summary = tdf.groupby("team_id", dropna=False).agg(
                    Assigned=("task_id", "count"),
                    Completed=("status", lambda x: (x == "Reviewed").sum()),
                    Passed=("assessment_status", lambda x: (x == "Passed").sum()),
                    Need_Revision=("assessment_status", lambda x: (x == "Need Revision").sum()),
                    Failed=("assessment_status", lambda x: (x == "Fail").sum())
                ).reset_index()
                team_summary["Completion %"] = (
                    100 * team_summary["Completed"] / team_summary["Assigned"]
                ).round(1)
                st.dataframe(team_summary, use_container_width=True, hide_index=True)
                st.plotly_chart(
                    px.bar(
                        team_summary, x="team_id", y=["Assigned", "Completed"],
                        barmode="group", title="Team Workload and Completed Tasks"
                    ),
                    use_container_width=True
                )
                tdf = tdf.copy()
                tdf["Risk Level"] = tdf.apply(risk_level, axis=1)
                team_risk = tdf.groupby(["team_id", "Risk Level"]).size().reset_index(name="Task Count")
                st.plotly_chart(
                    px.bar(
                        team_risk, x="team_id", y="Task Count", color="Risk Level",
                        barmode="stack",
                        category_orders={"Risk Level": ["Low", "Medium", "High"]},
                        title="Team Work — Low / Medium / High Risk"
                    ),
                    use_container_width=True
                )
        st.caption(
            "Risk is calculated automatically from due date, task status, priority, "
            "and assessment result; it is an operational indicator, not a formal risk audit."
        )

    elif page == "Attendance":
        with connect() as c:
            q = "SELECT a.*,i.full_name,i.team_id FROM attendance a JOIN interns i USING(intern_id)"
            args = []
            if user["role"] == "team_lead":
                q += " WHERE i.team_id=?"
                args = [user["team_id"]]
            elif user["role"] == "intern":
                q += " WHERE i.intern_id=?"
                args = [user["intern_id"]]
            rows = [dict(x) for x in c.execute(q, args)]
        eligible = [x for x in rows if x["status"] in ("Present", "Absent")]
        pct = 100 * sum(x["status"] == "Present" for x in eligible) / len(eligible) if eligible else 0
        st.metric("Attendance %", f"{pct:.1f}%", "Leave and Holiday excluded")
        if user["role"] in ("admin", "team_lead"):
            with connect() as c:
                query = "SELECT intern_id,full_name FROM interns WHERE active=1"
                args = ()
                if user["role"] == "team_lead":
                    query += " AND team_id=?"
                    args = (user["team_id"],)
                ins = [dict(x) for x in c.execute(query, args)]
            if ins:
                with st.form("att"):
                    intern = st.selectbox(
                        "Intern", ins,
                        format_func=lambda x: f"{x['intern_id']} — {x['full_name']}"
                    )
                    day = st.date_input("Date")
                    status = st.selectbox("Attendance", ["Present", "Absent", "Leave", "Holiday"])
                    remarks = st.text_input("Remarks")
                    ok = st.form_submit_button("Record attendance")
                if ok:
                    with connect() as c:
                        c.execute(
                            """INSERT INTO attendance
                               (intern_id,attendance_date,status,remarks,recorded_by)
                               VALUES(?,?,?,?,?)
                               ON CONFLICT(intern_id,attendance_date) DO UPDATE SET
                               status=excluded.status,remarks=excluded.remarks,
                               recorded_by=excluded.recorded_by""",
                            (intern["intern_id"], str(day), status, remarks, user["username"])
                        )
                    audit(user["username"], "record_attendance", "attendance",
                          f"{intern['intern_id']}:{day}")
                    st.success("Attendance saved")
        if user["role"] in ("admin", "team_lead"):
            st.subheader("Automated attendance reconciliation")
            auto_day = st.date_input("Attendance date to reconcile", value=date.today(), key="auto_attendance_day")
            if st.button("Auto-mark missing attendance as Absent"):
                with connect() as c:
                    if user["role"] == "team_lead":
                        eligible_ids = [r[0] for r in c.execute(
                            "SELECT intern_id FROM interns WHERE active=1 AND team_id=?",
                            (user["team_id"],)
                        )]
                    else:
                        eligible_ids = [r[0] for r in c.execute(
                            "SELECT intern_id FROM interns WHERE active=1"
                        )]
                    inserted = 0
                    for iid in eligible_ids:
                        cur = c.execute(
                            """INSERT OR IGNORE INTO attendance
                               (intern_id,attendance_date,status,remarks,recorded_by)
                               VALUES(?,?, 'Absent','Automatically marked: no attendance record',?)""",
                            (iid, str(auto_day), user["username"])
                        )
                        inserted += cur.rowcount
                audit(
                    user["username"], "auto_attendance_reconcile", "attendance",
                    str(auto_day), details=f"{inserted} absent record(s) added"
                )
                st.success(
                    f"Automation complete: {inserted} missing attendance record(s) marked Absent. "
                    "Existing records were preserved."
                )
                st.rerun()
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    elif page == "Assessments":
        df = pd.DataFrame([x for x in tasks(user) if x["status"] in ("Submitted", "Reviewed")])
        st.dataframe(df, use_container_width=True, hide_index=True)
        if user["role"] in ("admin", "team_lead") and not df.empty:
            opts = df.to_dict("records")
            with st.form("review"):
                t = st.selectbox("Task", opts, format_func=lambda x: f"{x['task_id']} — {x['title']}")
                result = st.selectbox("Result", ["Passed", "Need Revision", "Fail"])
                comment = st.text_area("Reviewer comments")
                ok = st.form_submit_button("Save review")
            if ok:
                if not allowed(user, t["team_id"], t["intern_id"]):
                    st.error("Unauthorized team scope")
                else:
                    t.update(
                        status="Reviewed", assessment_status=result,
                        reviewer_comments=comment, reviewed_by=user["username"]
                    )
                    save_task(t, user["username"])
                    st.success("Assessment saved")
                    st.rerun()

    elif page == "Deadline Monitoring":
        for key, label in [
            ("overdue", "Overdue"), ("due_today", "Due today"),
            ("upcoming", "Upcoming"), ("review_pending", "Review pending"),
            ("revision", "Need Revision")
        ]:
            st.subheader(label)
            rows = deadlines(user)[key]
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No records")
            if rows:
                st.download_button(
                    f"Export {label}", pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                    f"{key}.csv", mime="text/csv", key=key
                )

    elif page == "Reports & Exports":
        kind = st.selectbox(
            "Report", [
                "Intern Master", "Task Register", "Pending Tasks", "Overdue Tasks",
                "Upcoming Deadlines", "Assessment Report", "Team Follow-up"
            ]
        )
        if kind == "Intern Master":
            with connect() as c:
                query = "SELECT * FROM interns"
                args = ()
                if user["role"] == "team_lead":
                    query += " WHERE team_id=?"
                    args = (user["team_id"],)
                elif user["role"] == "intern":
                    query += " WHERE intern_id=?"
                    args = (user["intern_id"],)
                rows = [dict(x) for x in c.execute(query, args)]
        else:
            rows = tasks(user)
            if kind == "Pending Tasks":
                rows = [x for x in rows if x["status"] != "Reviewed"]
            elif kind == "Overdue Tasks":
                rows = deadlines(user)["overdue"]
            elif kind == "Upcoming Deadlines":
                rows = deadlines(user)["upcoming"]
            elif kind == "Assessment Report":
                rows = [x for x in rows if x["status"] == "Reviewed"]
            elif kind == "Team Follow-up":
                rows = deadlines(user)["overdue"] + deadlines(user)["review_pending"] + deadlines(user)["revision"]

        df = pd.DataFrame(rows)
        st.caption(f"{len(rows)} record(s)")
        if rows:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No records match selected report")
        st.download_button(
            "Download CSV", df.to_csv(index=False).encode("utf-8-sig"),
            kind.lower().replace(" ", "_") + ".csv", mime="text/csv"
        )

        from openpyxl import Workbook
        xbuf = BytesIO()
        xw = Workbook()
        xws = xw.active
        xws.title = "Report"
        if not df.empty:
            xws.append(list(df.columns))
            for rec in df.fillna("").itertuples(index=False, name=None):
                xws.append([str(v) if not isinstance(v, (int, float)) else v for v in rec])
        else:
            xws.append(["No records match selected report"])
        xw.save(xbuf)
        st.download_button(
            "Download Excel (.xlsx)", xbuf.getvalue(),
            kind.lower().replace(" ", "_") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        buff = BytesIO()
        doc = SimpleDocTemplate(buff, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        story = [
            Paragraph("DefineInfoTech Pvt. Ltd. — " + kind, styles["Title"]),
            Paragraph("Generated " + str(date.today()), styles["Normal"])
        ]
        if rows:
            cols = list(rows[0])[:7]
            story.append(
                Table(
                    [cols] + [[str(r.get(k, ""))[:45] for k in cols] for r in rows[:150]],
                    repeatRows=1,
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102D58")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), .4, colors.grey),
                        ("FONTSIZE", (0, 0), (-1, -1), 7)
                    ])
                )
            )
        else:
            story.append(Paragraph("No records match selected filters.", styles["Normal"]))
        doc.build(story)
        st.download_button(
            "Download PDF", buff.getvalue(),
            kind.lower().replace(" ", "_") + ".pdf", mime="application/pdf"
        )
        audit(user["username"], "report_export", "report", kind)

    elif page == "Excel Import Center":
        from services.csv_import_service import import_records, SCHEMAS
        st.subheader("Validated CSV / Excel Import")
        st.info(
            "Import is atomic: if any row has a validation error, the entire file is rejected "
            "and nothing is saved. Existing IDs are not overwritten."
        )
        template_dir = Path(__file__).parent / "templates"
        for base, cols in SCHEMAS.items():
            c1, c2 = st.columns(2)
            with c1:
                csv_path = template_dir / (base + "_template.csv")
                if csv_path.exists():
                    st.download_button(
                        "Download " + base + ".csv", csv_path.read_bytes(),
                        base + ".csv", mime="text/csv", key="csv_" + base
                    )
            with c2:
                xlsx_path = template_dir / (base + "_template.xlsx")
                if xlsx_path.exists():
                    st.download_button(
                        "Download " + base + ".xlsx", xlsx_path.read_bytes(),
                        base + ".xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="xlsx_" + base
                    )
        up = st.file_uploader(
            "Upload completed CSV or XLSX template — import runs automatically",
            type=["csv", "xlsx"], key="actual_import_upload"
        )
        if up:
            if up.size > 5 * 1024 * 1024:
                st.error("Maximum upload size is 5 MB.")
            else:
                import hashlib
                payload = up.getvalue()
                signature = hashlib.sha256(up.name.encode("utf-8") + payload).hexdigest()
                if st.session_state.get("last_import_signature") != signature:
                    with st.spinner("Automatically validating and importing records…"):
                        result = import_records(up.name, payload, user["username"])
                        st.session_state["last_import_result"] = result
                        st.session_state["last_import_signature"] = signature
                    if result["imported"]:
                        st.success(f"Automatic import complete: {result['imported']} record(s) saved to the database.")
                        st.rerun()
                    elif result["errors"]:
                        st.error("Automatic import stopped safely. No records were saved because validation failed.")
                else:
                    st.caption("This exact file has already been processed in this session; it will not be imported twice automatically.")
        result = st.session_state.get("last_import_result")
        if result:
            st.markdown("### Latest import result")
            a, b, c, d = st.columns(4)
            a.metric("Records read", result["read"])
            b.metric("Imported", result["imported"])
            c.metric("Rejected", result["rejected"])
            d.metric("Duplicates", result["duplicates"])
            if result["imported"]:
                st.success(f"Successfully imported {result['imported']} record(s) into the database.")
            elif result["read"] and result["errors"]:
                st.error("Import cancelled. No rows were saved because validation failed.")
            if result["errors"]:
                err_df = pd.DataFrame(result["errors"])
                st.dataframe(err_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download validation error report",
                    err_df.to_csv(index=False).encode("utf-8-sig"),
                    "import_validation_errors.csv", "text/csv", key="download_import_errors"
                )
            if result["read"] == 0 and not result["errors"]:
                st.warning("The uploaded file did not contain any records.")

    elif page == "Data Quality":
        issues = []
        with connect() as c:
            checks = [
                (
                    "Task intern/team mismatch",
                    "SELECT t.task_id FROM tasks t JOIN interns i ON i.intern_id=t.intern_id WHERE t.team_id<>i.team_id",
                    "Correct the task team to match the assigned intern team"
                ),
                (
                    "Task references missing intern",
                    "SELECT t.task_id FROM tasks t LEFT JOIN interns i ON i.intern_id=t.intern_id WHERE i.intern_id IS NULL",
                    "Assign the task to an existing intern"
                ),
                (
                    "Reviewed without review history",
                    "SELECT t.task_id FROM tasks t WHERE t.status='Reviewed' AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.task_id=t.task_id)",
                    "Open Assessments and save the review again"
                ),
                (
                    "Due date before assigned date",
                    "SELECT task_id FROM tasks WHERE due_date<assigned_date",
                    "Set the due date to the assigned date or later"
                ),
                (
                    "Passed assessment not reviewed",
                    "SELECT task_id FROM tasks WHERE assessment_status='Passed' AND status<>'Reviewed'",
                    "Review and finalize the task status"
                )
            ]
            for label, sql, resolution in checks:
                issues += [
                    {"Issue": label, "Record": r[0], "Resolution": resolution}
                    for r in c.execute(sql)
                ]
        if issues:
            st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
        else:
            st.success("No detected data-quality issues")

    elif page == "Audit Logs":
        with connect() as c:
            st.dataframe(
                pd.read_sql_query(
                    "SELECT * FROM audit_logs ORDER BY audit_id DESC LIMIT 1000", c
                ),
                use_container_width=True, hide_index=True
            )

    elif page == "User Management":
        with connect() as c:
            st.dataframe(
                pd.read_sql_query(
                    "SELECT username,role,intern_id,team_id,active FROM users", c
                ),
                use_container_width=True, hide_index=True
            )
        with st.form("useradd"):
            u = st.text_input("Username")
            p = st.text_input("Temporary password (12+ chars)", type="password")
            role = st.selectbox("Role", ["admin", "team_lead", "intern"])
            iid = st.text_input("Intern ID (intern role)")
            tid = st.text_input("Team ID (team lead role)")
            ok = st.form_submit_button("Create user")
        if ok:
            if len(p) < 12:
                st.error("Password must be at least 12 characters")
            else:
                with connect() as c:
                    c.execute(
                        "INSERT INTO users(username,password_hash,role,intern_id,team_id) VALUES(?,?,?,?,?)",
                        (u, hash_password(p), role, iid or None, tid or None)
                    )
                audit(user["username"], "create_user", "user", u)
                st.success("User created")

    elif page == "Backup & Settings":
        if st.button("Create verified backup"):
            st.success("Backup created: " + str(backup()))
        st.caption(
            "Restoration is intentionally a documented offline operation: stop Streamlit, "
            "validate backup with SQLite PRAGMA integrity_check, retain a safety copy, "
            "then replace the configured database file."
        )

    elif page == "User Guide":
        st.markdown("""- Create teams first, then intern records, then tasks.
- Completion = Passed assessments / all assigned tasks × 100.
- Attendance = Present / (Present + Absent) × 100; Leave and Holiday are excluded.
- Overdue excludes submitted/reviewed tasks; due today is separate; upcoming window defaults to 3 calendar days.
- Sample records are provided for demonstration and can be replaced with your organisation's records.
- Company branding: the supplied original DefineInfoTech logo is included at `assets/dit_logo.png` and appears in the sidebar. The app opens directly without a login screen.""")

    elif page == "Change Password":
        with st.form("pw"):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password (12+ chars)", type="password")
            ok = st.form_submit_button("Change")
        if ok:
            with connect() as c:
                r = c.execute(
                    "SELECT password_hash FROM users WHERE username=?",
                    (user["username"],)
                ).fetchone()
            if not r or not verify_password(old, r[0]):
                st.error("Current password incorrect")
            elif len(new) < 12:
                st.error("Password must be 12+ characters")
            else:
                with connect() as c:
                    c.execute(
                        "UPDATE users SET password_hash=? WHERE username=?",
                        (hash_password(new), user["username"])
                    )
                st.success("Password updated")


main(st.session_state.user)