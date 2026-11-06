"""Work in the background (the import, a build of the app): its output kept in memory for the page to follow."""

import subprocess
import threading
import time
import uuid

from flask import abort, jsonify

from .core import app, BASE

_jobs = {}
_jobs_lock = threading.Lock()


def start_job(kind, cmd, env=None, **details):
    """Run a command in the background; its output is kept for the page to poll. cmd may also be a list of commands,
    run one after the other until one fails (the setup's import, then the song list). env, when given, is the
    commands' environment. details (a build's address) stay with the job for the page."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "state": "running", "log": [], "started": time.time(), **details}
    with _jobs_lock:
        _jobs[job_id] = job
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
    # Keep the last twenty jobs' output; older ones are of no use to anyone.
    with _jobs_lock:
        for old in sorted(_jobs.values(), key=lambda j: j["started"])[:-20]:
            if old["state"] != "running":
                del _jobs[old["id"]]
    return job_id


def running_build():
    with _jobs_lock:
        return next((j for j in _jobs.values() if j["kind"] == "build" and j["state"] == "running"), None)


@app.route(BASE + "/jobs/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id) or abort(404)
    return jsonify(state=job["state"], log=job["log"][-200:])
