"""Work in the background (the import, a build of the app, a restore through the API): its output kept in memory for the
page, or the API, to follow."""

import subprocess
import threading
import time
import uuid

from flask import abort, jsonify

from .core import app, BASE

_jobs = {}
_jobs_lock = threading.Lock()

# What a job's view leaves out: its function for the words of a failure.
PRIVATE = ("explain",)


def _new(kind, explain, details):
    """A new job, running, kept with the others."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "state": "running", "log": [], "started": time.time(), "explain": explain,
           **details}
    with _jobs_lock:
        _jobs[job_id] = job
    return job


def _forget_old():
    """Keep the last twenty jobs' output; older ones are of no use to anyone."""
    with _jobs_lock:
        for old in sorted(_jobs.values(), key=lambda j: j["started"])[:-20]:
            if old["state"] != "running":
                del _jobs[old["id"]]


def start_job(kind, cmd, env=None, explain=None, **details):
    """Run a command in the background; its output is kept for the page to poll. cmd may also be a list of commands,
    run one after the other until one fails (the setup's import, then the song list). env, when given, is the
    commands' environment. explain: what a failed job's output means in the page's words (a function of its lines).
    details (a build's address) stay with the job for the page."""
    job = _new(kind, explain, details)
    # One command, or several in order.
    cmds = cmd if cmd and isinstance(cmd[0], (list, tuple)) else [cmd]

    def run():
        try:
            for one in cmds:
                # The tools write UTF-8 (-X utf8); a byte that is not cannot stop the job's log.
                p = subprocess.Popen(one, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     errors="replace", env=env)
                for line in p.stdout:
                    job["log"].append(line.rstrip())
                if p.wait() != 0:
                    job["state"] = "failed"
                    return
            job["state"] = "done"
        except OSError as e:
            job["log"].append(str(e))
            job["state"] = "failed"

    threading.Thread(target=run, daemon=True).start()
    _forget_old()
    return job["id"]


def start_task(kind, work, **details):
    """Run work(say) in a thread of this process as a job: say(line) adds a line to its output. work returns None when
    it did what it was for, or the words of why it did not (the job then failed, and says that as its why). An exception
    fails the job too, and is in the log of this service. details stay with the job, as start_job's do."""
    job = _new(kind, None, details)

    def run():
        try:
            why = work(lambda line: job["log"].append(str(line)))
        except Exception as e:  # noqa: BLE001 - whatever stops the work, the job must not stay running for ever
            app.logger.exception("job %s failed", job["id"])
            why = f"{e.__class__.__name__}: {e}"
        if why:
            job["why"] = str(why)
        job["state"] = "failed" if why else "done"

    threading.Thread(target=run, daemon=True).start()
    _forget_old()
    return job["id"]


def running_build():
    with _jobs_lock:
        return next((j for j in _jobs.values() if j["kind"] == "build" and j["state"] == "running"), None)


def why_failed(job):
    """Why a job failed, in the page's language, when anything says so: a task's own words, or what a command's lines
    mean (its explain); None for a job that did not fail."""
    if job["state"] != "failed":
        return None
    if job.get("why"):
        return job["why"]
    return job["explain"](job["log"]) if job.get("explain") else None


def view(job):
    """A job as the API shows it: id, kind, state (running, done or failed), started (a Unix time), its last 200 lines of
    output, why it failed, and its details (a build's address, an import's path, a restore's backup)."""
    out = {k: v for k, v in job.items() if k not in PRIVATE and k != "log"}
    out.update(started=int(job["started"]), log=job["log"][-200:], why=why_failed(job))
    return out


def listing():
    """The jobs this service keeps (its last twenty, and every one running), newest first."""
    with _jobs_lock:
        jobs = list(_jobs.values())
    return sorted(jobs, key=lambda j: j["started"], reverse=True)


@app.route(BASE + "/jobs/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id) or abort(404)
    # Why it failed, in the page's language: the programs' own lines are in English.
    return jsonify(state=job["state"], log=job["log"][-200:], why=why_failed(job))
