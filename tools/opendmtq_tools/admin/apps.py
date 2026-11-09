"""The App page: the builds of the phone app, the one on offer, the installer for Windows that the site hands out, what the
last build said, and the QR code. Each form's work is a function (start_build, prune, delete) that the API calls as well
(api.py)."""

import datetime
import json
import os
import re
import threading
import time

from flask import Response, abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import NotFound

from .. import windows_client
from . import core, jobs
from .core import Refused, app, BASE, changed, human, safe_name, t, tp


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
    """The download page by the address all phones use (localhost or a link without a host is no use to a friend), with its
    port over HTTPS (windows_client.site_url)."""
    return windows_client.site_url(core.site_scheme(health) == "https", core.PUBLIC_HOST) + "/opendmtq/download.php"


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


def start_build(typed):
    """Starts a build of the app, as the App page's form does: for the address typed (as pasted from a browser's address
    bar too), or this server's when it is empty. Returns (the job's id, the address). Refused: a build running already,
    or an import (it may be bringing the client in) or the server's own build at its start, as the setup refuses them.
    The look and the start are one step under the setup's lock: two at once cannot start two builders on one output."""
    # The setup's lock and its words for what runs (setup imports this module: it is asked for here, once it is there).
    from . import setup
    with setup._busy_lock:
        if jobs.running_build():
            raise Refused(409, "build_running", t("app.already"))
        why = setup.busy()
        if why:
            raise Refused(409, "busy", why)
        return _start_build(typed)


def _start_build(typed):
    """start_build's own work, once nothing else runs (the caller holds the setup's lock)."""
    # What was pasted from a browser's address bar is meant the same.
    host = re.sub(r"^https?://", "", (typed or "").strip()).rstrip("/") or core.PUBLIC_HOST
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,74}(:[0-9]{1,5})?", host):
        raise Refused(400, "bad_host", t("app.bad_host", host=host), host=host)
    # No base APK at all (data/apk/base missing counts as empty): say so rather than start a
    # build that cannot work.
    base = os.path.join(core.APK, "base")
    if not any(f.lower().endswith(".apk") for f in (os.listdir(base) if os.path.isdir(base) else [])):
        raise Refused(409, "no_client", t("app.no_base"), host=host)
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
    return jobs.start_job("build", cmd, host=host), host


def offer_state(listed=None):
    """What the App page says of the app on offer, at its top: (its build or None, (light, words) or None, why the last
    build failed or None). The words: a failed rebuild, an app for an address that is not this server's, or right.
    listed: builds() when the caller has it already."""
    listed = builds() if listed is None else listed
    offer = next((b for b in listed if b["current"]), None)
    failed = build_error()
    if offer is None:
        state = None
    elif failed:
        state = ("wait", tp("app.offer_failed", why=failed))
    elif offer["host"] != core.PUBLIC_HOST:
        state = ("bad", tp("app.offer_other", host=offer["host"]))
    else:
        state = ("on", tp("app.offer_ok", host=core.PUBLIC_HOST))
    return offer, state, failed


@app.route(BASE + "/app", methods=["GET", "POST"])
def app_page():
    if request.method == "POST":
        try:
            job, _ = start_build(request.form.get("host", ""))
        except Refused as e:
            flash(e.words, e.tone)
            # The address field keeps what was refused, or what a build waits for a client for.
            return redirect(url_for("app_page", host=e.extra["host"]) if "host" in e.extra else url_for("app_page"))
        return redirect(url_for("app_page", job=job))
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
    offer, state, _ = offer_state(listed)
    typed = job.get("host") or request.args.get("host") or ""
    return render_template("app.html", offer=offer, state=state, windows=windows_offer(offer), others=[b for b in listed if not b["current"]],
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
    """Deletes every build but the one the portal offers."""
    try:
        n, freed = prune()
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("app_page"))
    flash(t("app.pruned", n=n, size=human(freed)), "ok")
    return redirect(url_for("app_page"))


def prune():
    """Deletes every build but the one the portal offers: (how many, bytes freed). Not while one is being made, or with no
    way to tell which is on offer: it would take that one too."""
    listed = builds()
    if jobs.running_build() or not any(b["current"] for b in listed):
        if jobs.running_build():
            raise Refused(409, "build_running", t("app.already"))
        raise Refused(409, "offer_unknown", t("app.prune_unknown"))
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
    return n, freed


def download(name):
    """One build's file, as its download button gives it (404 for a name that is no build)."""
    return send_file(safe_name(name, os.path.join(core.APK, "out"), ".apk"), as_attachment=True,
                     mimetype="application/vnd.android.package-archive")


@app.route(BASE + "/app/download/<name>")
def app_download(name):
    return download(name)


def windows_offer(offer=None):
    """The installer for Windows (the PC client) the site hands out, as the builder describes it in windows.json beside the
    app (tools/opendmtq_tools/windows_client.py), or None: a server without it, or its file not there whole. It is the same
    for every app, so `offer` (the app on offer, which the App page passes) changes nothing. The API's GET /app and
    GET /app/windows ask here too (api.py)."""
    return windows_client.offered(os.path.join(core.APK, "out"))


def installer_scheme():
    """How the installer reaches the site: as the server's health says (core.site_scheme). A health check that gave no
    answer is asked again; still none, the site is taken to have HTTPS when the server's own authority is there and the
    edge has not said it runs without HTTPS (as the health check itself decides), when the router serves it
    (ROUTER_TLS=yes) or when this admin page itself came over HTTPS, so that a moment's miss never sends players'
    passwords over plain HTTP."""
    health = core.server_health()
    if not health or "https" not in health:
        health = core.server_health(fresh=True)
    if health and "https" in health:
        return core.site_scheme(health)
    # No answer from the server: what this side knows of how it is reached.
    folder = os.environ.get("OPENDMTQ_HTTPS") or "/srv/https"
    own = bool(windows_client.own_ca(folder)) and not os.path.isfile(os.path.join(folder, "edge-plain"))
    tls = own or os.environ.get("ROUTER_TLS") == "yes" or request.headers.get("X-Forwarded-Proto") == "https" or request.is_secure
    return "https" if tls and not core.lan_only(core.PUBLIC_HOST) else "http"


def windows_download():
    """The installer for Windows as the site hands it to computers, set up for this server: the server's address on its end
    (windows_client.preset), under a file name that says which server it is for (404 when there is none)."""
    made = windows_offer()
    if not made:
        abort(404)
    path = os.path.join(core.APK, "out", os.path.basename(made["file"]))
    https = installer_scheme() == "https"
    # Over HTTPS, the server's own authority goes with the address: the launcher trusts it for this server alone.
    tail = windows_client.preset(windows_client.site_url(https, core.PUBLIC_HOST), core.server_name(),
                                 windows_client.own_ca() if https else "")

    # Opened now: the length said and the bytes sent are the same file's, even if the builder swaps it meanwhile.
    try:
        f = open(path, "rb")
    except OSError:
        abort(404)
    size = os.fstat(f.fileno()).st_size

    def body():
        # The installer a megabyte at a time, then its end.
        with f:
            for block in iter(lambda: f.read(1 << 20), b""):
                yield block
        yield tail

    name = windows_client.download_name(core.PUBLIC_HOST)
    return Response(body(), mimetype="application/vnd.microsoft.portable-executable",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Content-Length": str(size + len(tail))})


@app.route(BASE + "/app/windows")
def app_windows():
    return windows_download()


@app.route(BASE + "/app/delete/<name>", methods=["POST"])
def app_delete(name):
    try:
        delete(name)
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("app_page"))
    flash(t("app.deleted", name=name), "ok")
    return redirect(url_for("app_page"))


def delete(name):
    """Deletes one build and its manifest. Refused: no such build, or the one the portal offers."""
    try:
        path = safe_name(name, os.path.join(core.APK, "out"), ".apk")
    except NotFound:
        raise Refused(404, "build_not_found", t("app.gone"))
    if any(b["file"] == name and b["current"] for b in builds()):
        raise Refused(409, "on_offer", t("app.is_public"))
    os.remove(path)
    if os.path.exists(path + ".json"):
        os.remove(path + ".json")
    changed("app_delete:", name)
