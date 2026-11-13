# auth.py
# accounts: sign up, log in, log out.
#
# this file is a flask "Blueprint" - basically a mini app with its own
# routes that app.py plugs in with app.register_blueprint(). it just keeps
# all the login stuff in one place instead of making app.py huge.
# the only difference you'll notice: in url_for you write "auth.login"
# instead of just "login".
#
# HOW PASSWORDS ARE STORED (important!)
# we never save the actual password. generate_password_hash() scrambles it
# into something like "scrypt:32768:8:1$Xy7...$a9f..." which can't be turned
# back into the password. when you log in, check_password_hash() scrambles
# what you typed the same way and checks if it matches.
# so even if someone stole cafe.db they wouldn't see anyone's password.

import os
import re
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

bp = Blueprint("auth", __name__)

# letters, numbers, _ and . only, 3-20 long. keeps urls like /u/mina clean
USERNAME_RULE = re.compile(r"^[A-Za-z0-9_.]{3,20}$")
MIN_PASSWORD = 6


@bp.before_app_request
def load_logged_in_user():
    # runs before EVERY page. if you're logged in, the session cookie has
    # your user_id - we look you up and put you in g.user so every route
    # and template can use it. not logged in -> g.user is None.
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = db.get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    # put @login_required under @app.route(...) on any page that needs an
    # account. if you're not logged in it sends you to the login page, and
    # ?next=... remembers where you were going so we can send you back after.
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            # requests sent by javascript (like the heart button) can't follow
            # a redirect to the login page, so tell them where to go instead
            if request.headers.get("X-Requested-With") == "fetch":
                # urlparse(...).path turns "http://site/feed" into just "/feed"
                back_to = urlparse(request.referrer or "/").path
                return {"login": url_for("auth.login", next=back_to)}, 401
            flash("Log in first!")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(url):
    # only allow redirecting to our own pages (starting with "/"), otherwise
    # someone could make a link like /login?next=https://evil-site.com
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return url_for("home")


def log_in(user_id):
    # session.clear() first throws away the old session, so a cookie someone
    # else set before you logged in can't be reused (look up "session fixation")
    session.clear()
    session["user_id"] = user_id
    session.permanent = True


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")
    oshis = request.form.get("oshis", "").strip()

    error = None
    if not USERNAME_RULE.match(username):
        error = "Username needs 3-20 letters, numbers, _ or ."
    elif len(password) < MIN_PASSWORD:
        error = f"Password needs at least {MIN_PASSWORD} characters."
    elif password != password2:
        error = "The two passwords don't match."
    else:
        # COLLATE NOCASE = "Mina" and "mina" count as the same name
        taken = db.get_db().execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if taken:
            error = "That username is taken :("

    if error:
        flash(error)
        # send back what they typed (except passwords) so they don't retype it all
        return render_template("signup.html", form=request.form)

    con = db.get_db()
    cur = con.execute(
        "INSERT INTO users (username, password_hash, oshis) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), oshis),
    )
    con.commit()

    log_in(cur.lastrowid)
    flash(f"Welcome to Oshi Collective, {username}!")
    return redirect(url_for("home"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", next=request.args.get("next", ""))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = db.get_db().execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()

    # NOTE: same message whether the username or the password was wrong,
    # so nobody can use the login form to find out which usernames exist
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Wrong username or password.")
        return render_template("login.html", next=request.form.get("next", ""), username=username)

    log_in(user["id"])
    return redirect(safe_next(request.form.get("next")))


@bp.route("/logout", methods=["POST"])
def logout():
    # POST, not a normal link - otherwise any site could log you out by
    # putting <img src="yoursite/logout"> on their page
    session.clear()
    flash("Logged out. See you soon ♡")
    return redirect(url_for("landing"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("change_password.html")

    current = request.form.get("current", "")
    new = request.form.get("new", "")
    new2 = request.form.get("new2", "")

    # ask for the current password first - otherwise anyone who found your
    # phone unlocked with the site open could change it and lock you out
    if not check_password_hash(g.user["password_hash"], current):
        flash("Your current password is wrong.")
    elif len(new) < MIN_PASSWORD:
        flash(f"New password needs at least {MIN_PASSWORD} characters.")
    elif new != new2:
        flash("The two new passwords don't match.")
    elif new == current:
        flash("That's the same as your current password!")
    else:
        con = db.get_db()
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new), g.user["id"]))
        con.commit()
        # start a fresh session (same as logging in again) - good habit after
        # anything security related
        log_in(g.user["id"])
        flash("Password changed ♡")
        return redirect(url_for("profile", username=g.user["username"]))

    return render_template("change_password.html")


@bp.route("/account/delete", methods=["GET", "POST"])
@login_required
def delete_account():
    if request.method == "GET":
        return render_template("delete_account.html")

    # two checks so nobody deletes an account by accident (or on someone
    # else's unlocked phone): the password, and ticking the "I understand" box
    if not check_password_hash(g.user["password_hash"], request.form.get("password", "")):
        flash("Wrong password - your account was NOT deleted.")
        return render_template("delete_account.html")
    if not request.form.get("confirm"):
        flash("Tick the box to confirm.")
        return render_template("delete_account.html")

    user_id = g.user["id"]
    con = db.get_db()

    # files to delete from static/uploads once the database part is done:
    # their profile picture + every photo they posted
    photos = [r["photo"] for r in con.execute(
        "SELECT photo FROM comments WHERE user_id = ? AND photo IS NOT NULL", (user_id,))]
    if g.user["avatar"]:
        photos.append(g.user["avatar"])

    # everything that points at THEIR comments (likes/reports from other
    # people on them) has to go first, then the comments themselves
    their_comments = "SELECT id FROM comments WHERE user_id = ?"
    for table in ("likes", "reports", "hidden_comments"):
        con.execute(f"DELETE FROM {table} WHERE comment_id IN ({their_comments})", (user_id,))
    con.execute("DELETE FROM comments WHERE user_id = ?", (user_id,))

    # then everything THEY did: likes, reports, hides, saves, follows (both ways)
    for table in ("likes", "reports", "hidden_comments", "saved_cafes", "cafe_reports"):
        con.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    con.execute("DELETE FROM follows WHERE follower_id = ? OR followee_id = ?", (user_id, user_id))

    # cafes they added STAY on the site (other people review them), they
    # just don't belong to anyone anymore
    con.execute("UPDATE cafes SET added_by = NULL WHERE added_by = ?", (user_id,))

    con.execute("DELETE FROM users WHERE id = ?", (user_id,))
    con.commit()

    folder = current_app.config["UPLOAD_FOLDER"]
    for name in photos:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            os.remove(path)

    session.clear()  # log them out
    flash("Your account was deleted. Bye for now ♡")
    return redirect(url_for("landing"))
