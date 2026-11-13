# admin.py
# the admin page (/admin) and the admin-only buttons on cafe pages.
#
# who's an admin? anyone with users.is_admin = 1. there's no button on the
# site to become one (that would be a security hole) - set it from the terminal:
#     .venv\Scripts\python db.py make-admin USERNAME
#
# admins can:
#   - see reported cafes + reported comments in one place
#   - edit any cafe (the check is in edit_cafe() in app.py)
#   - delete any comment (delete_comment() in app.py)
#   - delete a cafe, or merge a duplicate into the real one (below)

from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import db
from auth import login_required
from cleanup import remove_cafe

bp = Blueprint("admin", __name__)


def admin_required(view):
    # like @login_required, but you also have to be an admin.
    # not an admin -> 403 forbidden (we don't even hint the page exists)
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_cafe_or_404(cafe_id):
    cafe = db.get_db().execute("SELECT * FROM cafes WHERE id = ?", (cafe_id,)).fetchone()
    if cafe is None:
        abort(404)
    return cafe


@bp.route("/admin")
@admin_required
def dashboard():
    con = db.get_db()

    # open cafe reports, newest first, grouped by cafe so a cafe reported
    # 5 times shows up once with 5 reasons under it
    rows = con.execute(
        """SELECT r.*, cafes.name AS cafe_name, cafes.area AS cafe_area, users.username AS reporter
           FROM cafe_reports r
           JOIN cafes ON cafes.id = r.cafe_id
           JOIN users ON users.id = r.user_id
           WHERE r.resolved = 0
           ORDER BY r.created_at DESC, r.id DESC"""
    ).fetchall()
    cafe_reports = {}
    for r in rows:
        group = cafe_reports.setdefault(r["cafe_id"], {"id": r["cafe_id"], "name": r["cafe_name"],
                                                       "area": r["cafe_area"], "reports": []})
        group["reports"].append(r)

    # comments with at least one report, most reported first
    comment_reports = con.execute(
        """SELECT comments.*, cafes.name AS cafe_name,
                  COUNT(reports.id) AS report_count,
                  GROUP_CONCAT(DISTINCT reports.reason) AS reasons
           FROM comments
           JOIN reports ON reports.comment_id = comments.id
           JOIN cafes ON cafes.id = comments.cafe_id
           GROUP BY comments.id
           ORDER BY report_count DESC, comments.created_at DESC"""
    ).fetchall()

    return render_template("admin.html", cafe_reports=list(cafe_reports.values()),
                           comment_reports=comment_reports, report_limit=db.REPORT_LIMIT)


@bp.route("/admin/cafe/<int:cafe_id>/resolve", methods=["POST"])
@admin_required
def resolve_cafe_reports(cafe_id):
    # "dismiss" - the reports were checked and nothing needed changing
    # (or it was fixed with the edit button). they stay in the database as resolved.
    con = db.get_db()
    con.execute("UPDATE cafe_reports SET resolved = 1 WHERE cafe_id = ?", (cafe_id,))
    con.commit()
    flash("Reports marked as done.")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.route("/admin/comment/<int:comment_id>/dismiss", methods=["POST"])
@admin_required
def dismiss_comment_reports(comment_id):
    # the comment is fine - clear its reports so it's not hidden for everyone anymore
    con = db.get_db()
    con.execute("DELETE FROM reports WHERE comment_id = ?", (comment_id,))
    con.commit()
    flash("Reports cleared - the comment stays.")
    return redirect(url_for("admin.dashboard"))


@bp.route("/admin/cafe/<int:cafe_id>/delete", methods=["POST"])
@admin_required
def delete_cafe(cafe_id):
    cafe = get_cafe_or_404(cafe_id)
    remove_cafe(cafe_id)  # see cleanup.py - takes the comments, photos, saves with it
    flash(f"Deleted {cafe['name']}.")
    return redirect(url_for("admin.dashboard"))


@bp.route("/admin/cafe/<int:cafe_id>/merge", methods=["POST"])
@admin_required
def merge_cafe(cafe_id):
    """
    Merge a duplicate INTO the real cafe:
      everything people posted on the duplicate moves to the real one,
      then the duplicate is deleted. the real cafe keeps its own info.
    """
    duplicate = get_cafe_or_404(cafe_id)
    try:
        keep_id = int(request.form.get("into", ""))
    except ValueError:
        keep_id = None
    if keep_id is None or keep_id == cafe_id:
        flash("Pick which café to merge it into.")
        return redirect(url_for("cafe_page", cafe_id=cafe_id))
    keep = get_cafe_or_404(keep_id)

    con = db.get_db()
    # 1. comments/posts move over (their likes/reports come too, since those
    #    point at the comment, not the cafe)
    con.execute("UPDATE comments SET cafe_id = ? WHERE cafe_id = ?", (keep_id, cafe_id))
    # 2. saves move over. "OR IGNORE" skips people who'd saved both
    con.execute("""INSERT OR IGNORE INTO saved_cafes (user_id, cafe_id, created_at)
                   SELECT user_id, ?, created_at FROM saved_cafes WHERE cafe_id = ?""", (keep_id, cafe_id))
    con.commit()
    # 3. the duplicate is now empty - delete it (and its leftover saves/reports/cover)
    remove_cafe(cafe_id)

    flash(f"Merged {duplicate['name']} into {keep['name']}.")
    return redirect(url_for("cafe_page", cafe_id=keep_id))
