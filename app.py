"""Meadow House Repairs - a small Flask app for reporting and tracking repairs.

Jobs are stored in a JSON file (data/jobs.json by default) so they survive
page refreshes and server restarts. All user text is rendered through Jinja's
autoescaping, so HTML-looking input is shown as plain text.
"""

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

HOUSE_NAME = "Meadow House"
PRIORITIES = ("Normal", "Urgent")
STATUS_NEW = "New"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"
STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED)
MAX_TEXT = 1000

BASE_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

class JobStore:
    """Reads and writes jobs to a JSON file. Each write is atomic."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self):
        if not self.path.exists():
            return {"next_id": 1, "jobs": []}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def all_jobs(self):
        with self.lock:
            return self._load()["jobs"]

    def get(self, job_id):
        for job in self.all_jobs():
            if job["id"] == job_id:
                return job
        return None

    def create(self, description, reporter, priority):
        with self.lock:
            data = self._load()
            now = _now()
            job = {
                "id": f"MH-{data['next_id']:04d}",
                "house": HOUSE_NAME,
                "created_at": now,
                "description": description,
                "reporter": reporter,
                "priority": priority,
                "status": STATUS_NEW,
                "latest_note": None,
                "completion_note": None,
                "history": [
                    {"at": now, "status": STATUS_NEW,
                     "event": f"Repair reported by {reporter}", "note": None},
                ],
            }
            data["next_id"] += 1
            data["jobs"].append(job)
            self._save(data)
            return job

    def update(self, job_id, change):
        """Apply `change(job)` to one job only, then save."""
        with self.lock:
            data = self._load()
            for job in data["jobs"]:
                if job["id"] == job_id:
                    change(job)
                    self._save(data)
                    return job
            return None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _clean(value):
    return (value or "").strip()


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

def create_app(data_file=None):
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(16)
    store = JobStore(data_file or os.environ.get("MEADOW_DATA_FILE")
                     or BASE_DIR / "data" / "jobs.json")
    app.config["STORE"] = store

    @app.template_filter("when")
    def format_when(iso):
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b %Y at %H:%M:%S")

    @app.template_filter("status_class")
    def status_class(status):
        return "status-" + status.lower().replace(" ", "-")

    def render_index(errors=None, values=None, status=200):
        status_filter = request.args.get("status", "All")
        jobs = list(reversed(store.all_jobs()))  # newest first
        counts = {s: sum(1 for j in jobs if j["status"] == s) for s in STATUSES}
        counts["All"] = len(jobs)
        if status_filter in STATUSES:
            jobs = [j for j in jobs if j["status"] == status_filter]
        else:
            status_filter = "All"
        return render_template(
            "index.html",
            jobs=jobs,
            counts=counts,
            status_filter=status_filter,
            statuses=STATUSES,
            priorities=PRIORITIES,
            errors=errors or {},
            values=values or {"priority": "Normal"},
            max_text=MAX_TEXT,
        ), status

    def render_job(job, errors=None, values=None, status=200):
        return render_template(
            "job.html",
            job=job,
            errors=errors or {},
            values=values or {},
            max_text=MAX_TEXT,
        ), status

    def load_job_or_404(job_id):
        job = store.get(job_id)
        if job is None:
            abort(404)
        return job

    @app.get("/")
    def index():
        return render_index()

    @app.post("/jobs")
    def create_job():
        values = {
            "description": request.form.get("description", ""),
            "reporter": request.form.get("reporter", ""),
            "priority": request.form.get("priority", ""),
        }
        description = _clean(values["description"])
        reporter = _clean(values["reporter"])
        priority = values["priority"]

        errors = {}
        if not description:
            errors["description"] = ("Enter a description of the repair. "
                                     "It cannot be blank or only spaces.")
        elif len(description) > MAX_TEXT:
            errors["description"] = f"Description must be {MAX_TEXT} characters or fewer."
        if not reporter:
            errors["reporter"] = ("Enter the name of the person reporting the repair. "
                                  "It cannot be blank or only spaces.")
        elif len(reporter) > 200:
            errors["reporter"] = "Reporter name must be 200 characters or fewer."
        if priority not in PRIORITIES:
            errors["priority"] = "Choose a priority: Normal or Urgent."
            values["priority"] = ""

        if errors:
            return render_index(errors=errors, values=values, status=400)

        job = store.create(description, reporter, priority)
        flash(("created", job["id"]))
        return redirect(url_for("index") + "#created")

    @app.get("/jobs/<job_id>")
    def view_job(job_id):
        return render_job(load_job_or_404(job_id))

    @app.post("/jobs/<job_id>/start")
    def start_job(job_id):
        job = load_job_or_404(job_id)
        if job["status"] != STATUS_NEW:
            return render_job(job, errors={
                "start": f"This job is already {job['status']}."}, status=400)

        def change(j):
            j["status"] = STATUS_IN_PROGRESS
            j["history"].append({"at": _now(), "status": STATUS_IN_PROGRESS,
                                 "event": "Moved to In Progress", "note": None})

        store.update(job_id, change)
        flash(("saved", f"Job {job_id} moved to In Progress."))
        return redirect(url_for("view_job", job_id=job_id))

    @app.post("/jobs/<job_id>/progress")
    def add_progress(job_id):
        job = load_job_or_404(job_id)
        raw = request.form.get("note", "")
        note = _clean(raw)
        errors = {}
        if job["status"] == STATUS_COMPLETED:
            errors["note"] = "This job is completed, so progress notes can no longer be added."
        elif not note:
            errors["note"] = "Enter a progress note. It cannot be blank or only spaces."
        elif len(note) > MAX_TEXT:
            errors["note"] = f"Progress note must be {MAX_TEXT} characters or fewer."
        if errors:
            return render_job(job, errors=errors, values={"note": raw}, status=400)

        moved = job["status"] == STATUS_NEW

        def change(j):
            j["status"] = STATUS_IN_PROGRESS
            j["latest_note"] = note
            j["history"].append({
                "at": _now(), "status": STATUS_IN_PROGRESS,
                "event": ("Moved to In Progress with progress note" if moved
                          else "Progress note added"),
                "note": note,
            })

        store.update(job_id, change)
        msg = "Progress note saved"
        msg += " and job moved to In Progress." if moved else ". Status: In Progress."
        flash(("saved", msg))
        return redirect(url_for("view_job", job_id=job_id))

    @app.post("/jobs/<job_id>/complete")
    def complete_job(job_id):
        job = load_job_or_404(job_id)
        raw = request.form.get("completion_note", "")
        note = _clean(raw)
        errors = {}
        if job["status"] == STATUS_COMPLETED:
            errors["completion_note"] = "This job is already completed."
        elif not note:
            errors["completion_note"] = (
                "Enter a completion note explaining what was done. "
                "It cannot be blank or only spaces. The job has not been completed.")
        elif len(note) > MAX_TEXT:
            errors["completion_note"] = f"Completion note must be {MAX_TEXT} characters or fewer."
        if errors:
            return render_job(job, errors=errors,
                              values={"completion_note": raw}, status=400)

        def change(j):
            j["status"] = STATUS_COMPLETED
            j["completion_note"] = note
            j["latest_note"] = note
            j["history"].append({"at": _now(), "status": STATUS_COMPLETED,
                                 "event": "Marked as Completed", "note": note})

        store.update(job_id, change)
        flash(("saved", f"Job {job_id} marked as Completed."))
        return redirect(url_for("view_job", job_id=job_id))

    @app.errorhandler(404)
    def not_found(_):
        return render_template("not_found.html"), 404

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
