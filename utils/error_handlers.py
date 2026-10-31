from __future__ import annotations

import logging

from flask import render_template, request


def register_error_handlers(app, *, db, ErrorLog, current_user_fn) -> None:
    marker = "_reman_error_handlers_registered"
    if app.extensions.get(marker):
        return

    @app.errorhandler(500)
    def handle_internal_error(error):
        user = None
        try:
            user = current_user_fn()
        except Exception:
            user = None
        logging.exception(
            "Unhandled exception on %s (user=%s): %s",
            request.path,
            getattr(user, "id", None),
            error,
        )
        try:
            entry = ErrorLog(
                path=request.path,
                message=str(error),
                user_id=getattr(user, "id", None),
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return render_template("error.html"), 500

    app.extensions[marker] = True
