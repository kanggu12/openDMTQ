"""Work in the background (the import, a build of the app, a restore, a backup made on its page, a change to the songs): its
output kept in memory for the page, or the API, to follow."""

import subprocess
import threading
import time
import uuid

from flask import abort, flash, jsonify, redirect, url_for

from . import core
from .core import app, BASE

_jobs = {}
_jobs_lock = threading.Lock()

# What a job's view leaves out: its function for the words of a failure, the sign that it has ended, and what a page's
# job says on its page (in that page's language, with its markup).
PRIVATE = ("explain", "ended", "said", "shown")

# How long a page's form waits for the job it started: one that ends in this time answers as it always did, with the page
# and what it says; a longer one (a backup with gigabytes of added songs) is followed on the page (?job=), and holds no
# request while it runs.
PAGE_WAIT = 3


def _new(kind, explain, details):
    """A new job, running, kept with the others."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "state": "running", "log": [], "started": time.time(), "explain": explain,
           "ended": threading.Event(), **details}
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
        finally:
            # Whoever waits for it (a page's form) hears at once.
            job["ended"].set()

    threading.Thread(target=run, daemon=True).start()
    _forget_old()
    return job["id"]


def start_task(kind, work, **details):
    """Run work(say) in a thread of this process as a job: say(line) adds a line to its output. work returns None when
    it did what it was for, or the words of why it did not (the job then failed, and says that as its why). An exception
    fails the job too, and is in the log of this service. details stay with the job, as start_job's do."""
    job = _new(kind, None, details)
    _run(job, work)
    return job["id"]


def _run(job, work):
    """work(say) for job in a thread of its own, as start_task describes."""
    def run():
        try:
            why = work(lambda line: job["log"].append(str(line)))
        except Exception as e:  # noqa: BLE001 - whatever stops the work, the job must not stay running for ever
            app.logger.exception("job %s failed", job["id"])
            why = f"{e.__class__.__name__}: {e}"
        if why:
            job["why"] = str(why)
        job["state"] = "failed" if why else "done"
        # Whoever waits for it (a page's form) hears at once.
        job["ended"].set()

    threading.Thread(target=run, daemon=True).start()
    _forget_old()


def start_page_task(kind, work, **details):
    """A form's work as a job, for a page and the API alike (start_task): work(say) runs in the language of the request
    that started it, and notes its changes by whoever sent it, as it would in that request, which has ended by then
    (core.acting_as). It returns what the page says of it, [(tone, words)] in the page's words, and whether it did what it
    was for. Those words are the job's log as plain text, its why when it failed, and what its page shows once it has
    ended (flash_said)."""
    speaking, who = core.lang(), core.acting_who()
    job = _new(kind, None, details)

    def run(say):
        with core.acting_as(speaking, who):
            said, ok = work(say)
        # What the page shows once the job has ended, and the same words in its log for the API.
        job["said"] = said
        for _, words in said:
            say(core.plain(words))
        if ok:
            return None
        # Failed: why, in its own words, the first that says what went wrong.
        bad = [words for tone, words in said if tone == "bad"] or [words for _, words in said]
        return core.plain(bad[0]) if bad else "failed"

    _run(job, run)
    return job["id"]


def answer(job_id, endpoint):
    """The answer to a page's form that started a job (start_page_task): its page with what the job said once it ends
    within PAGE_WAIT, as a quick one always answered; otherwise its page following it (?job=)."""
    job = _jobs.get(job_id)
    if job and job["ended"].wait(PAGE_WAIT):
        flash_said(job)
        return redirect(url_for(endpoint))
    return redirect(url_for(endpoint, job=job_id))


def nothing_to_follow(job_id):
    """For a page's ?job=: True when there is no job to follow there, as it has ended (what it said is now on the page) or
    this service no longer knows it (it started again); the page is then shown without it. False while it runs."""
    job = _jobs.get(job_id)
    if job and job["state"] == "running":
        return False
    if job:
        flash_said(job)
    return True


def flash_said(job):
    """What a page's job said, on its page, once: its own words, or for one stopped by an error of its own (in this
    service's log), that it did not work."""
    if job.get("shown"):
        return
    job["shown"] = True
    said = job.get("said")
    if said is None:
        said = [("bad", core.t("job.failed"))] if job["state"] == "failed" else []
    for tone, words in said:
        if words is not None:
            flash(words, tone)


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
