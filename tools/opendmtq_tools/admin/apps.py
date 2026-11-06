"""The App page: the builds of the phone app, the one on offer, what the last build said, and the QR code."""

import datetime
import json
import os
import re
import threading
import time

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import NotFound

from . import core, jobs
from .core import app, BASE, changed, human, safe_name, t, tp


def builds():
    """Every app build with its manifest, newest first, and which one the portal offers."""
    out_dir = os.path.join(core.APK, "out")
    latest = {}
    try:
        with open(os.path.join(out_dir, "latest.json"), encoding="utf-8") as f:
            latest = json.load(f)
    except (OSError, ValueError):
        pass
    current = latest.get("file")
    items = []
    for f in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
        if f.startswith("OpenDMTQ-") and f.endswith(".apk"):
            meta = {}
            try:
                with open(os.path.join(out_dir, f + ".json"), encoding="utf-8") as m:
                    meta = json.load(m)
            except (OSError, ValueError):
                pass
            # The public build's manifest is latest.json too, which the portal reads.
            if f == current:
                meta = {**meta, **latest}
            # Builds made before per-build manifests: the address is in the file name.
            if not meta:
                m = re.match(r"OpenDMTQ-(.+)-v(\d{4})\.(\d\d)\.(\d\d)\.apk$", f)
                if m:
                    meta = {"host": re.sub(r"-(\d+)$", r":\1", m.group(1)), "built_at": f"{m.group(2)}-{m.group(3)}-{m.group(4)}"}
            # runtime: the arm32 runtime version inside, for phones without 32-bit support (patchers
            # before it wrote no such field, and added none).
            items.append({"file": f, "host": meta.get("host", "?"), "built_at": meta.get("built_at", ""),
                          "size": os.path.getsize(os.path.join(out_dir, f)), "sha256": meta.get("sha256", ""),
                          "runtime": meta.get("runtime"), "label": meta.get("label"), "current": f == current,
                          "mtime": os.path.getmtime(os.path.join(out_dir, f))})
    return sorted(items, key=lambda b: b["mtime"], reverse=True)

# A status still saying "building" after this long belongs to a run that was cut off: the same limit
# as the builder's STALE_BUILD and the portal's build_failed() in server/portal/lib.php.
STALE_BUILD = 15 * 60


def base_changed_since(when):
    """True when data/apk/base changed after when (a time.time()): a client came in or went. Its folder's own time
    says so, since a client linked in keeps the time of the file it came from."""
    try:
        # A second's slack: the builder writes whole seconds, the disk keeps fractions.
        return os.path.getmtime(os.path.join(core.APK, "base")) >= when + 1
    except OSError:
        return False


def build_error():
    """Why the builder's last run for this address failed (data/apk/out/build.json, which the portal
    and ./opendmtq doctor read too), or None. Also when an app for this address exists: a failed
    rebuild (new patcher, base APK, runtime bundle or key) leaves players with the earlier app."""
    try:
        with open(os.path.join(core.APK, "out", "build.json"), encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict) or status.get("host") != core.PUBLIC_HOST:
        return None
    try:
        started = float(status.get("time") or 0)
    except (TypeError, ValueError):
        started = 0
    # A client brought in since that run: its outcome says nothing about building from this one (the build at the
    # first start fails for want of a client, before the setup imports it).
    if base_changed_since(started):
        return None
    if status.get("state") == "failed":
        return status.get("error") or t("build.no_reason")
    # The portal already tells players this one failed; the owner learns it here too.
    if status.get("state") == "building" and time.time() - started > STALE_BUILD:
        return t("build.part_way")
    return None


def invite_text(url, name, password):
    """The message to send a friend with their new account: where to sign in and get the app, their ID and password."""
    return tp("invite.text", url=url, id=name, password=password)


def friends_address(health):
    """The download page by the address all phones use (localhost or a link without a host is no use to a friend)."""
    return f"{core.site_scheme(health)}://{core.PUBLIC_HOST}/opendmtq/download.php"


def icon_for_the_app_on_offer():
    """The launcher icon of the app the portal offers, when it was built before the builder kept one beside it."""
    out = os.path.join(core.APK, "out")
    try:
        with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
            name = json.load(f)["file"]
        if not os.path.exists(os.path.join(out, "app-icon.png")) and os.path.isfile(os.path.join(out, name)):
            from .. import patch_apk
            patch_apk.write_icon(os.path.join(out, name), os.path.join(out, "app-icon.png"))
    except (OSError, ValueError, KeyError, TypeError):
        pass

threading.Thread(target=icon_for_the_app_on_offer, name="app-icon", daemon=True).start()


@app.route(BASE + "/qr.svg")
def invite_qr():
    """The app's QR code, for showing to a friend next to the screen."""
    path = os.path.join(core.APK, "out", "download-qr.svg")
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/svg+xml", max_age=60)


@app.route(BASE + "/app", methods=["GET", "POST"])
def app_page():
    if request.method == "POST":
        if jobs.running_build():
            flash(t("app.already"), "bad")
            return redirect(url_for("app_page"))
        # What was pasted from a browser's address bar is meant the same.
        host = re.sub(r"^https?://", "", request.form.get("host", "").strip()).rstrip("/") or core.PUBLIC_HOST
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,74}(:[0-9]{1,5})?", host):
            flash(t("app.bad_host", host=host), "bad")
            return redirect(url_for("app_page", host=host))
        # No base APK at all (data/apk/base missing counts as empty): say so rather than start a
        # build that cannot work.
        base = os.path.join(core.APK, "base")
        if not any(f.lower().endswith(".apk") for f in (os.listdir(base) if os.path.isdir(base) else [])):
            flash(t("app.no_base"), "bad")
            return redirect(url_for("app_page", host=host))
        if host == core.PUBLIC_HOST:
            # The server's own address: through the builder, as at every start, so that build.json
            # (what the portal, this dashboard and ./opendmtq doctor say about the app) tells this
            # build's outcome too, and a failure noted earlier goes away once a build succeeds. It
            # reads BASE_APK from the environment.
            cmd = core.PYTHON + ["-m", "opendmtq_tools.builder", "--force", "--host", host]
        else:
            cmd = core.PYTHON + ["-m", "opendmtq_tools.patch_apk", "--host", host,
                   "--stamp", datetime.date.today().strftime("%Y.%m.%d")]
            # BASE_APK in .env picks one when data/apk/base holds several different clients, else the newest (as for
            # the builder).
            if os.environ.get("BASE_APK"):
                cmd += ["--base", os.environ["BASE_APK"]]
            # Only a build for the server's own address becomes the portal's download.
            cmd.append("--keep-latest")
        changed("app_page:", host)
        return redirect(url_for("app_page", job=jobs.start_job("build", cmd, host=host)))
    # Back from a build that finished: it says so once, on the page with the new list.
    built = jobs._jobs.get(request.args.get("built", ""))
    if built:
        flash(t("app.done", host=built.get("host", core.PUBLIC_HOST)), "ok")
        return redirect(url_for("app_page"))
    # A build this page does not know (from before a restart): nothing to follow.
    wanted = request.args.get("job", "")
    if wanted and wanted not in jobs._jobs:
        return redirect(url_for("app_page"))
    # Without one asked for, the one running: from another tab, or coming back, the page follows it too.
    if not wanted:
        with jobs._jobs_lock:
            wanted = next((i for i, j in jobs._jobs.items() if j["kind"] == "build" and j["state"] == "running"), "")
    # The address field keeps what was typed for another address (or refused) here.
    job = jobs._jobs.get(wanted, {})
    listed = builds()
    offer = next((b for b in listed if b["current"]), None)
    # What is said of the app on offer: a failed rebuild, an app for an address that is not this server's, or right.
    failed = build_error()
    if offer is None:
        state = None
    elif failed:
        state = ("wait", tp("app.offer_failed", why=failed))
    elif offer["host"] != core.PUBLIC_HOST:
        state = ("bad", tp("app.offer_other", host=offer["host"]))
    else:
        state = ("on", tp("app.offer_ok", host=core.PUBLIC_HOST))
    typed = job.get("host") or request.args.get("host") or ""
    return render_template("app.html", offer=offer, state=state, others=[b for b in listed if not b["current"]],
                           job=wanted or None, running=jobs.running_build(), host=typed if typed != core.PUBLIC_HOST else "",
                           icon=os.path.isfile(os.path.join(core.APK, "out", "app-icon.png")))


@app.route(BASE + "/app/icon.png")
def app_icon():
    """The launcher icon of the app on offer (kept beside it by the builder), for the App page."""
    path = os.path.join(core.APK, "out", "app-icon.png")
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png", max_age=60)


@app.route(BASE + "/app/prune", methods=["POST"])
def app_prune():
    """Deletes every build but the one the portal offers. Not while one is being made, or with no way to tell which is on
    offer: it would take that one too."""
    listed = builds()
    if jobs.running_build() or not any(b["current"] for b in listed):
        flash(t("app.already") if jobs.running_build() else t("app.prune_unknown"), "bad")
        return redirect(url_for("app_page"))
    n = freed = 0
    for b in listed:
        if b["current"]:
            continue
        path = os.path.join(core.APK, "out", b["file"])
        try:
            size = os.path.getsize(path)
            os.remove(path)
            if os.path.exists(path + ".json"):
                os.remove(path + ".json")
            n += 1
            freed += size
        except OSError:
            pass
    if n:
        changed("app_prune:", str(n))
    flash(t("app.pruned", n=n, size=human(freed)), "ok")
    return redirect(url_for("app_page"))


@app.route(BASE + "/app/download/<name>")
def app_download(name):
    return send_file(safe_name(name, os.path.join(core.APK, "out"), ".apk"), as_attachment=True,
                     mimetype="application/vnd.android.package-archive")


@app.route(BASE + "/app/delete/<name>", methods=["POST"])
def app_delete(name):
    try:
        path = safe_name(name, os.path.join(core.APK, "out"), ".apk")
    except NotFound:
        flash(t("app.gone"), "bad")
        return redirect(url_for("app_page"))
    if any(b["file"] == name and b["current"] for b in builds()):
        flash(t("app.is_public"), "bad")
    else:
        os.remove(path)
        if os.path.exists(path + ".json"):
            os.remove(path + ".json")
        changed("app_delete:", name)
        flash(t("app.deleted", name=name), "ok")
    return redirect(url_for("app_page"))
