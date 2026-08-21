"""
Tiny monitoring dashboard.

  /          simple view — big status of the most recent scan (for the recipient)
  /details   full job history with sizes, errors, thumbnails (for you)
  /thumb/<job_id>  serves the page-1 thumbnail image
  /scans/<job_id>/view      serves the archived PDF inline (browser viewer)
  /scans/<job_id>/download  same file, as an attachment
  /scans/<job_id>/delete    POST — deletes the local archive copy permanently
  /settings  view/change the recipient email (stored in the DB, overrides
             RECIPIENT_EMAIL from .env without a restart)

No login — this is only as safe as the network it's reachable on (Tailscale
and/or LAN, see docs/SETUP.md). Don't expose it to the open internet. The
POST routes (settings, delete) still carry a double-submit-cookie CSRF
check so a malicious page in another tab can't drive them just because
your browser can reach the dashboard.
"""
import re
import secrets
from flask import Flask, render_template, send_file, abort, request, redirect, url_for, g
from pathlib import Path

from app.config import config
from app import db

app = Flask(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CSRF_COOKIE = "csrf_token"


@app.before_request
def _load_csrf_token():
    g.csrf_token = request.cookies.get(_CSRF_COOKIE) or secrets.token_urlsafe(32)


@app.after_request
def _persist_csrf_cookie(response):
    if request.cookies.get(_CSRF_COOKIE) != g.get("csrf_token"):
        response.set_cookie(_CSRF_COOKIE, g.csrf_token, samesite="Strict", httponly=True)
    return response


@app.context_processor
def _inject_csrf_token():
    return {"csrf_token": g.get("csrf_token", "")}


def _require_csrf():
    cookie_token = request.cookies.get(_CSRF_COOKIE, "")
    form_token = request.form.get("csrf_token", "")
    if not cookie_token or not secrets.compare_digest(cookie_token, form_token):
        abort(403)

STATUS_LABELS = {
    "received": ("Received", "neutral"),
    "ocr_running": ("Processing…", "working"),
    "uploading": ("Uploading…", "working"),
    "done": ("Sent \u2705", "good"),
    "failed": ("Failed \u274c", "bad"),
}


def _fmt_size(num_bytes):
    if not num_bytes:
        return "—"
    mb = num_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"


def _fmt_time(ts):
    if not ts:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%b %d, %I:%M %p")


def _enrich(job):
    j = dict(job)
    label, css_class = STATUS_LABELS.get(j["status"], (j["status"], "neutral"))
    j["status_label"] = label
    j["status_class"] = css_class
    j["created_at_fmt"] = _fmt_time(j["created_at"])
    j["original_size_fmt"] = _fmt_size(j["original_size_bytes"])
    j["compressed_size_fmt"] = _fmt_size(j["compressed_size_bytes"])
    if j["original_size_bytes"] and j["compressed_size_bytes"]:
        saved_pct = 100 * (1 - j["compressed_size_bytes"] / j["original_size_bytes"])
        j["saved_pct"] = round(saved_pct)
    else:
        j["saved_pct"] = None
    return j


@app.route("/")
def index():
    latest = db.get_latest_job()
    job = _enrich(latest) if latest else None
    return render_template("index.html", job=job)


@app.route("/details")
def details():
    jobs = [_enrich(j) for j in db.list_jobs(limit=100)]
    return render_template("details.html", jobs=jobs)


@app.route("/thumb/<int:job_id>")
def thumb(job_id):
    job = db.get_job(job_id)
    if not job or not job["thumbnail_path"]:
        abort(404)
    path = Path(job["thumbnail_path"])
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/png")


def _archived_pdf_path(job_id: int) -> Path:
    job = db.get_job(job_id)
    if not job or not job["archive_path"]:
        abort(404)
    path = Path(job["archive_path"])
    if not path.exists():
        abort(404)
    return path


@app.route("/scans/<int:job_id>/view")
def view_scan(job_id):
    return send_file(_archived_pdf_path(job_id), mimetype="application/pdf")


@app.route("/scans/<int:job_id>/download")
def download_scan(job_id):
    path = _archived_pdf_path(job_id)
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=path.name)


@app.route("/scans/<int:job_id>/delete", methods=["POST"])
def delete_scan(job_id):
    _require_csrf()
    job = db.get_job(job_id)
    if job and job["archive_path"]:
        path = Path(job["archive_path"])
        if path.exists():
            path.unlink()
        db.update_job(job_id, archive_path=None)
    return redirect(url_for("details"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    error = None
    saved = False
    if request.method == "POST":
        _require_csrf()
        new_email = request.form.get("recipient_email", "").strip()
        if new_email and _EMAIL_RE.match(new_email):
            db.set_setting("recipient_email", new_email)
            saved = True
        else:
            error = "Enter a valid email address."

    return render_template(
        "settings.html",
        recipient_email=db.get_recipient_email(),
        is_override=db.get_setting("recipient_email") is not None,
        error=error,
        saved=saved,
    )


def main():
    config.ensure_dirs()
    db.init_db()
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)


if __name__ == "__main__":
    main()
