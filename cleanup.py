# cleanup.py
# deleting things properly. used by app.py (delete your comment) and
# admin.py (delete / merge cafes, remove comments).
#
# "properly" = also deleting the rows that point at the thing, and the photo
# files in static/uploads - otherwise the database fills up with half-deleted
# leftovers and the uploads folder with photos nobody can see.

import os

from flask import current_app

import db


def delete_upload(name):
    """Delete one file from static/uploads (does nothing if it's already gone)."""
    if name:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], name)
        if os.path.exists(path):
            os.remove(path)


def remove_comments(where, params):
    """
    Deletes comments + their likes/reports/hides + their photo files.
      remove_comments("id = ?", (5,))        -> one comment
      remove_comments("cafe_id = ?", (3,))   -> every comment on a cafe
    NOTE: `where` gets pasted into the sql, so only ever pass text written in
    the code - user input goes in `params`.
    """
    con = db.get_db()
    rows = con.execute(f"SELECT id, photo FROM comments WHERE {where}", params).fetchall()
    for c in rows:
        # the rows that point at the comment have to go first, then the comment
        for table in ("reports", "hidden_comments", "likes"):
            con.execute(f"DELETE FROM {table} WHERE comment_id = ?", (c["id"],))
        con.execute("DELETE FROM comments WHERE id = ?", (c["id"],))
    con.commit()
    for c in rows:
        delete_upload(c["photo"])


def remove_cafe(cafe_id):
    """Deletes a cafe and EVERYTHING on it: comments, photos, saves, reports, cover."""
    con = db.get_db()
    cover = con.execute("SELECT cover FROM cafes WHERE id = ?", (cafe_id,)).fetchone()
    remove_comments("cafe_id = ?", (cafe_id,))
    con.execute("DELETE FROM saved_cafes WHERE cafe_id = ?", (cafe_id,))
    con.execute("DELETE FROM cafe_reports WHERE cafe_id = ?", (cafe_id,))
    con.execute("DELETE FROM cafes WHERE id = ?", (cafe_id,))
    con.commit()
    if cover:
        delete_upload(cover["cover"])
