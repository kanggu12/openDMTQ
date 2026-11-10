"""The launcher's tools that change or delete what OpenDMTQ keeps on this PC: Repair, Clear game data, Start over and
Uninstall on the Help page, and the launcher's own update on the Launcher page.

Each waits while the files it changes are in use (app.files_in_use) and asks before it removes anything; the slow
part (counting, deleting, comparing, downloading) runs on a worker thread under a dialog that says what is under way,
and the window cannot be closed until it is done. The command line has the same tools (main.py), the deleting itself
is removal.py's and actions.py's.
"""

import logging
import threading

from opendmtq_client import actions, dialogs, updates

log = logging.getLogger("opendmtq_client")


def _in_background(app, message, glyph, job, then):
    """Run job() on a worker thread under a dialog that says what is under way, then then(result, error) on the
    window's thread with the dialog gone. The window is not closed meanwhile: the work would stop half done."""
    app.dialog = dialogs.Dialog(app.root, app.ui, "info", message, message, progress=True, glyph=glyph)
    app.updating = True

    def work():
        try:
            result, error = job(), None
        except Exception as e:  # noqa: BLE001  (shown in a dialog, never swallowed)
            log.exception("%s failed", job.__name__)
            result, error = None, e
        app.post(lambda: finished(result, error))

    def finished(result, error):
        app.updating = False
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        # A step of its own, out of the task pump: a question then() asks (after a count) waits for its answer, and the
        # pump would hand the window nothing from the other worker threads meanwhile.
        app.root.after(0, lambda: then(result, error))

    threading.Thread(target=work, daemon=True, name=job.__name__).start()


def _not_now(app):
    """True, said on the status line, while the files these tools change are in use (app.files_in_use): the game runs,
    from this window or the command line, or PLAY or a download is under way."""
    if app.files_in_use():
        app.set_status(app.words("help.reset.busy"), "warn")
        return True
    return False


def start_over(app):
    """Start over: after a question, every server's app goes and the launcher is as at a first start, the guide next
    in the language it speaks now (actions.reset)."""
    w = app.words
    if _not_now(app):
        return
    if not dialogs.ask(app, "danger", w("help.reset.title"), w("help.reset.ask"), w("help.reset.detail"),
                       w("help.reset.confirm"), glyph="restore"):
        return
    actions.reset(app.state)
    app.state.save()
    app.devices = None
    app.page = "play"
    app.show()


def repair_program(app):
    """Repair: the program's files compared with the installed package, what is missing or changed put back."""
    from opendmtq_client import repair
    w = app.words
    if _not_now(app):
        return

    def done(result, error):
        if error is not None:
            dialogs.tell(app, "error", w("help.repair"), w("help.repair.failed"), w.error(error))
        elif result.failed:
            dialogs.tell(app, "warn", w("help.repair"), w("help.repair.partly"),
                         w("help.repair.partly.detail", n=result.restored, failed=len(result.failed)))
        elif result.restored:
            # The running launcher goes on with the files it loaded; its next start reads the ones put back.
            detail = "help.repair.done.restart" if result.needs_restart else "help.repair.done.detail"
            dialogs.tell(app, "info", w("help.repair"), w("help.repair.done"), w(detail, n=result.restored))
        else:
            dialogs.tell(app, "info", w("help.repair"), w("help.repair.fine"),
                         w("help.repair.fine.detail", n=result.checked))
        # The player may be back.
        app.refresh_checks()

    _in_background(app, w("help.repair.working"), "restore", repair.run, done)


def clear_game_data(app):
    """Clear game data: the games' folders emptied but for the id this PC plays by, after a question that says how
    much goes."""
    from opendmtq_client import removal
    w = app.words
    if _not_now(app):
        return

    def counted(size, error):
        if error is not None:
            dialogs.tell(app, "error", w("help.clear"), w("failed.message"), w.error(error))
            return
        if not size:
            app.set_status(w("help.clear.none"), "normal", transient=True)
            return
        said = removal.megabytes(size)
        if not dialogs.ask(app, "danger", w("help.clear"), w("help.clear.ask"), w("help.clear.detail", size=said),
                           w("help.clear.confirm"), glyph="delete"):
            return

        def done(failed, error):
            if error is not None:
                dialogs.tell(app, "error", w("help.clear"), w("help.clear.partly"), w.error(error))
            elif failed:
                dialogs.tell(app, "warn", w("help.clear"), w("help.clear.partly"),
                             w("help.clear.partly.detail", n=len(failed), path=failed[0]))
            # The player's log went with the rest: its row comes back once the game has run.
            if app.page == "help":
                app.go("help")
            if error is None and not failed:
                # Said after the page is drawn again, whose ready check would otherwise take the line at once.
                app.set_status(w("help.clear.done", size=said), "ok", sticky=True)

        _in_background(app, w("help.clear.working"), "delete", removal.clear_game_data, done)

    # Counted at the press, as the game adds to its data each time it runs; on a worker thread, as a game's thousands
    # of files take a while on a disk that has not read them lately, and the window would stop answering meanwhile.
    _in_background(app, w("help.counting"), "delete", removal.game_data_size, counted)


def uninstall_program(app):
    """Uninstall: a question with two ways, the data kept or deleted with the program; then Velopack's uninstaller
    starts and the window closes for it."""
    from opendmtq_client import removal
    w = app.words
    if _not_now(app):
        return

    def start():
        try:
            removal.uninstall()
        except Exception as e:  # noqa: BLE001  (Update.exe that did not start: said, and the window stays)
            log.exception("the uninstaller did not start")
            dialogs.tell(app, "error", w("help.uninstall"), w("help.uninstall.failed"),
                         w("help.uninstall.failed.detail", error=w.error(e)))
            return
        app.leave()

    def deleted(failed, error):
        # From here on the window writes nothing, whatever the player does next (closing it during a dialog below too):
        # its copy of the settings, sign-ins and all, would bring the deleted folder back.
        app.state.discarded = True
        if error is not None:
            # Nothing is uninstalled after a deletion that stopped half way: the player can choose again.
            dialogs.tell(app, "error", w("help.uninstall"), w("help.uninstall.failed"), w.error(error))
            return
        if failed:
            dialogs.tell(app, "warn", w("help.uninstall"), w("help.uninstall.left"),
                         w("help.uninstall.left.detail", n=len(failed), folder=removal.data_root()))
        start()

    def counted(total, error):
        if error is not None:
            dialogs.tell(app, "error", w("help.uninstall"), w("failed.message"), w.error(error))
            return
        # Cancel first and the ring on it: Enter alone removes nothing.
        choice = dialogs.choose(app, "danger", w("help.uninstall"), w("help.uninstall.ask"),
                                w("help.uninstall.detail", size=removal.megabytes(total)),
                                [(w("help.uninstall.keep"), "keep", "warn"),
                                 (w("help.uninstall.all"), "all", "danger")], glyph="delete")
        if choice == "keep":
            # Written before the uninstaller starts: it closes what runs from the program's folder, this window too.
            app.state.save()
            start()
        elif choice == "all":
            _in_background(app, w("help.uninstall.working"), "delete", removal.delete_everything, deleted)

    # What Delete all would free, counted on a worker thread first (the games' folders may hold thousands of files).
    _in_background(app, w("help.counting"), "delete", removal.everything_size, counted)


def update_launcher(app, result):
    """The Launcher page's Update to vX: the update downloads under the launcher's own dialog, then the launcher closes
    and Velopack puts it in without a window of its own and starts the new launcher. False, and nothing started, while
    a game runs (from this window or the command line): the update replaces the player's files under it."""
    w = app.words
    if app.files_in_use():
        return False
    app.dialog = dialogs.Dialog(app.root, app.ui, "info", w("about.updating.title"),
                                w("about.updating.message", v=result.version), w("about.updating.detail"),
                                progress=True, glyph="update")
    # The window stays until the update is in Velopack's hands: closing it now would end the download.
    app.updating = True

    def work():
        try:
            updates.apply(result)
        except Exception as e:  # noqa: BLE001  (shown, never swallowed)
            log.exception("the update failed")
            app.post(lambda text=str(e): failed(text))
            return
        log.info("closing for the update to %s", result.version)
        app.post(done)

    def done():
        app.updating = False
        app.close()

    def failed(text):
        app.updating = False
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        dialogs.tell(app, "error", w("about.update_failed.title"), w("about.apply_failed", error=text))

    threading.Thread(target=work, daemon=True, name="update").start()
    return True
