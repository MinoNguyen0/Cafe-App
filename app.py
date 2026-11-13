# app.py
# this is the main file - run it with:  .venv\Scripts\python app.py
# then open http://127.0.0.1:5000 in your browser
#
# how flask works in one sentence: each @app.route(...) function runs when
# someone visits that url, and whatever it returns is what the browser shows.
# render_template() fills in an html file from the templates/ folder.
#
# the pages:
#   /             landing page (the big stars one)
#   /home         home: featured cafes, what's new, posts from people you follow
#   /feed         all the oshikatsu posts, with tabs
#   /cafes        search + filter cafes (the cards with colour palettes)
#   /map          the same cafes as pins on a map
#   /cafe/3       one cafe + its comments
#   /post         make a new post
#   /add          add a cafe
#   /cafe/3/edit  edit a cafe (links, map pin, photo...)
#   /u/mina       someone's profile
#   /signup /login /logout   -> in auth.py

import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from markupsafe import Markup
from werkzeug.utils import secure_filename

import admin
import auth
import db
from auth import login_required
from cleanup import delete_upload, remove_comments
from colours import OSHI_COLOURS, palette_matches
from places import clean_handle, clean_website, find_address, metres_apart, names_match

app = Flask(__name__)


def load_secret_key():
    # the secret key signs the login cookie so nobody can edit it to pretend
    # to be another user. it has to be random and SECRET, so instead of
    # writing it in the code we make a random one the first time and keep it
    # in secret_key.txt. (don't share or upload that file!)
    path = os.path.join(app.root_path, "secret_key.txt")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.config["SECRET_KEY"] = load_secret_key()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)  # stay logged in for 30 days
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB max per upload

ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
REPORT_REASONS = ["offensive / hateful", "spam", "not about this cafe", "other"]

app.register_blueprint(auth.bp)        # adds /signup, /login, /logout
app.register_blueprint(admin.bp)       # adds /admin and the admin buttons
app.teardown_appcontext(db.close_db)   # close the database after every request


# ---- CSRF protection ----
# problem: if you're logged in here and visit some evil website, that site
# could secretly submit a form to OUR site (e.g. "delete comment 5") and your
# browser would send your login cookie along with it.
# fix: every form we make includes a random token that only our pages know.
# a form coming from anywhere else won't have it, so we reject it.

@app.before_request
def check_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
        abort(400)


def csrf_input():
    # use {{ csrf_input() }} inside every <form method="post"> in the templates
    return Markup(f'<input type="hidden" name="csrf" value="{session["csrf"]}">')


app.jinja_env.globals["csrf_input"] = csrf_input


# ---- little helpers ----

def save_photo(file):
    """Save an uploaded image and return its filename (or None if no/bad file)."""
    if not file or file.filename == "":
        return None

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGES:
        return None

    # NOTE: two people could upload "IMG_0001.jpg" - adding a random bit to
    # the front stops the second one overwriting the first.
    # secure_filename strips out sneaky stuff like "../../" from the name.
    name = f"{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], name))
    return name


def delete_photo(name):
    # the actual deleting lives in cleanup.py so admin.py can use it too
    delete_upload(name)


def split_tags(text):
    # "Café, Japanese" -> ["Café", "Japanese"]
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def time_ago(timestamp):
    # "2026-11-13 11:02:29" -> "3 hours ago"
    # sqlite's CURRENT_TIMESTAMP is in UTC, so we compare against UTC now
    then = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - then).total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("min", 60)):
        if secs >= size:
            n = secs // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


# lets templates use these as filters, e.g. {{ cafe.tags | tags }}
app.jinja_env.filters["tags"] = split_tags
app.jinja_env.filters["ago"] = time_ago


def my_id():
    # -1 when logged out: no user has id -1, so "WHERE user_id = -1" matches nothing
    return g.user["id"] if g.user else -1


@app.context_processor
def add_saved_ids():
    # a "context processor" adds variables to EVERY template automatically.
    # saved_ids = the ids of the cafes you've hearted, so any page can colour
    # in the hearts with: {% if cafe.id in saved_ids %}
    if not g.user:
        return {"saved_ids": set()}
    rows = db.get_db().execute("SELECT cafe_id FROM saved_cafes WHERE user_id = ?", (g.user["id"],))
    return {"saved_ids": {r["cafe_id"] for r in rows}}


# every query that lists cafes starts with this. LEFT JOIN so cafes with zero
# comments still show up, and AVG/COUNT work out the star rating.
CAFE_SELECT = """
    SELECT cafes.*,
           AVG(comments.rating) AS avg_rating,
           COUNT(comments.id)   AS review_count
    FROM cafes
    LEFT JOIN comments ON comments.cafe_id = cafes.id
"""


def get_posts(where="1 = 1", params=(), order="comments.created_at DESC, comments.id DESC", limit=30):
    """
    Posts for the feed / home / profile pages.
    A "post" is just a comment that has a photo.

    where + params narrow it down, e.g. get_posts("comments.user_id = ?", (5,))
    NOTE: `where` and `order` get pasted straight into the sql, so only ever
    pass in text written here in the code - never something a user typed.
    user input always goes in `params` (the ? placeholders), which is safe.
    """
    sql = f"""
        SELECT comments.*,
               cafes.name     AS cafe_name,
               cafes.area     AS cafe_area,
               users.username AS author,
               users.avatar   AS author_avatar,
               (SELECT COUNT(*) FROM likes l WHERE l.comment_id = comments.id) AS like_count,
               EXISTS (SELECT 1 FROM likes l
                       WHERE l.comment_id = comments.id AND l.user_id = ?) AS liked_by_me
        FROM comments
        JOIN cafes ON cafes.id = comments.cafe_id
        LEFT JOIN users ON users.id = comments.user_id
        WHERE comments.photo IS NOT NULL
          AND comments.id NOT IN (SELECT comment_id FROM hidden_comments WHERE user_id = ?)
          AND (SELECT COUNT(*) FROM reports r WHERE r.comment_id = comments.id) < ?
          AND ({where})
        ORDER BY {order}
        LIMIT ?
    """
    return db.get_db().execute(sql, (my_id(), my_id(), db.REPORT_LIMIT, *params, limit)).fetchall()


def create_comment(cafe_id):
    """Shared by the cafe page form and the /post page. Returns an error message or None."""
    oshi = request.form.get("oshi", "").strip()
    body = request.form.get("body", "").strip()
    try:
        rating = int(request.form.get("rating", 0))
    except ValueError:
        rating = 0

    con = db.get_db()
    if con.execute("SELECT 1 FROM cafes WHERE id = ?", (cafe_id,)).fetchone() is None:
        return "Pick a cafe!"
    if not body or not 1 <= rating <= 5:
        return "Please add a comment and a star rating!"

    photo = save_photo(request.files.get("photo"))
    con.execute(
        "INSERT INTO comments (cafe_id, user_id, username, oshi, rating, body, photo) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cafe_id, g.user["id"], g.user["username"], oshi, rating, body, photo),
    )
    con.commit()  # nothing is actually saved until you commit!
    return None


# ---- main pages ----

@app.route("/")
def landing():
    # already logged in? skip the welcome screen
    if g.user:
        return redirect(url_for("home"))
    return render_template("landing.html")


@app.route("/home")
def home():
    con = db.get_db()

    # carousel at the top: the 5 best rated cafes
    featured = con.execute(
        CAFE_SELECT + " GROUP BY cafes.id ORDER BY avg_rating IS NULL, avg_rating DESC, cafes.id LIMIT 5"
    ).fetchall()

    # "what's new": the newest posts from everyone
    newest_posts = get_posts(limit=8)

    # "from people you follow": only posts by people you follow.
    # logged out or not following anyone -> empty, and the page shows placeholders
    following_posts = []
    if g.user:
        following_posts = get_posts(
            "comments.user_id IN (SELECT followee_id FROM follows WHERE follower_id = ?)",
            (g.user["id"],), limit=6,
        )

    return render_template("home.html", featured=featured,
                           newest_posts=newest_posts, following_posts=following_posts)


@app.route("/saved")
@login_required
def saved():
    # the star in the bottom nav. two tabs: cafes you hearted, posts you liked
    tab = "posts" if request.args.get("tab") == "posts" else "cafes"

    if tab == "cafes":
        # newest saves first. the JOIN on saved_cafes keeps only YOUR saved cafes
        items = db.get_db().execute(
            CAFE_SELECT.replace("FROM cafes", "FROM cafes JOIN saved_cafes s ON s.cafe_id = cafes.id AND s.user_id = ?")
            # rowid = the order rows were added, for saves in the same second
            + " GROUP BY cafes.id ORDER BY MAX(s.created_at) DESC, MAX(s.rowid) DESC",
            (g.user["id"],),
        ).fetchall()
    else:
        items = get_posts("comments.id IN (SELECT comment_id FROM likes WHERE user_id = ?)", (g.user["id"],), limit=60)

    return render_template("saved.html", tab=tab, items=items)


@app.route("/cafe/<int:cafe_id>/save", methods=["POST"])
@login_required
def save_cafe(cafe_id):
    # the heart on cafe cards. the form says saved=1 (save it) or saved=0 (unsave).
    # we send the state we WANT instead of "toggle", so tapping twice quickly
    # can't get the heart and the database out of sync
    con = db.get_db()
    if con.execute("SELECT 1 FROM cafes WHERE id = ?", (cafe_id,)).fetchone() is None:
        abort(404)

    want = request.form.get("saved") == "1"
    if want:
        con.execute("INSERT OR IGNORE INTO saved_cafes (user_id, cafe_id) VALUES (?, ?)", (g.user["id"], cafe_id))
    else:
        con.execute("DELETE FROM saved_cafes WHERE user_id = ? AND cafe_id = ?", (g.user["id"], cafe_id))
    con.commit()

    # the javascript in base.html wants JSON back, like the post likes
    if request.headers.get("X-Requested-With") == "fetch":
        return {"saved": want}
    return redirect(request.referrer or url_for("saved"))


FEED_TABS = {"foryou": "For You", "following": "Following", "oshis": "Your Oshis", "explore": "Explore"}


@app.route("/feed")
def feed():
    tab = request.args.get("tab", "foryou")
    if tab not in FEED_TABS:
        tab = "foryou"

    posts = []
    message = None  # shown instead of posts when a tab is empty for a reason

    if tab == "foryou":
        posts = get_posts()

    elif tab == "explore":
        # most liked first
        posts = get_posts(order="like_count DESC, comments.created_at DESC")

    elif not g.user:
        # the other two tabs need to know who you are
        message = "login"

    elif tab == "following":
        posts = get_posts(
            "comments.user_id IN (SELECT followee_id FROM follows WHERE follower_id = ?)",
            (g.user["id"],),
        )
        if not posts:
            message = "Follow people (tap their name on a post) to see their posts here."

    elif tab == "oshis":
        my_oshis = split_tags(g.user["oshis"])
        if not my_oshis:
            message = "Add your oshis on your profile page to fill this tab!"
        else:
            # builds "(comments.oshi LIKE ? OR comments.oshi LIKE ? ...)" - one per oshi
            where = "(" + " OR ".join(["comments.oshi LIKE ?"] * len(my_oshis)) + ")"
            posts = get_posts(where, [f"%{o}%" for o in my_oshis])
            if not posts:
                message = "No posts with your oshis yet - be the first!"

    return render_template("feed.html", posts=posts, tab=tab, tabs=FEED_TABS, message=message)


def filter_cafes():
    """
    Reads the filters from the url (e.g. ?q=matcha&area=CBD&colour=green) and
    returns the matching cafes. shared by the /cafes list and the /map page,
    so the same filters work on both.
    """
    q = request.args.get("q", "").strip()
    cuisine = request.args.get("cuisine", "")
    area = request.args.get("area", "")
    colour = request.args.get("colour", "")
    sort = request.args.get("sort", "")

    con = db.get_db()

    # "WHERE 1 = 1" is a little trick so every filter below can just
    # start with "AND ..." without worrying about which one comes first
    sql = CAFE_SELECT + " WHERE 1 = 1"
    params = []

    if q:
        # search matches cafe name/street/tags, OR anyone who reviewed it,
        # OR the oshi people tagged in their reviews (the "character" search)
        like = f"%{q}%"
        sql += """ AND (cafes.name LIKE ? OR cafes.address LIKE ? OR cafes.tags LIKE ?
                   OR cafes.id IN (SELECT cafe_id FROM comments
                                   WHERE oshi LIKE ? OR username LIKE ?))"""
        params += [like] * 5

    if cuisine:
        sql += " AND cafes.tags LIKE ?"
        params.append(f"%{cuisine}%")

    if area:
        sql += " AND cafes.area = ?"
        params.append(area)

    sql += " GROUP BY cafes.id"

    if sort == "top":
        # best rated first, cafes with no reviews go to the bottom
        sql += " ORDER BY avg_rating IS NULL, avg_rating DESC, review_count DESC"
    else:
        sql += " ORDER BY cafes.created_at DESC, cafes.id DESC"

    results = con.execute(sql, params).fetchall()

    # colour filtering is done in python, not sql, because we need the
    # "how close is this colour" maths from colours.py
    if colour in OSHI_COLOURS:
        target = OSHI_COLOURS[colour]
        results = [c for c in results if palette_matches(c["palette"].split(","), target)]

    # build the dropdown options from whatever cafes are in the database
    all_cafes = con.execute("SELECT tags, area FROM cafes").fetchall()

    current = {"q": q, "cuisine": cuisine, "area": area, "colour": colour, "sort": sort}

    # only the filters that are actually switched on (no empty ones), so links
    # built from this look like /map?area=CBD instead of /map?q=&cuisine=&area=CBD...
    keep = {k: v for k, v in current.items() if v}

    # same filters but with "top rated" flipped - for the top rated button
    top_toggle = {k: v for k, v in keep.items() if k != "sort"}
    if sort != "top":
        top_toggle["sort"] = "top"

    return {
        "cafes": results,
        "cuisines": sorted({t for row in all_cafes for t in split_tags(row["tags"])}),
        "areas": sorted({row["area"] for row in all_cafes}),
        "oshi_colours": OSHI_COLOURS,
        # pass the current filters back so the form remembers them
        "current": current,
        "keep": keep,
        "top_toggle": top_toggle,
    }


@app.route("/cafes")
def cafes():
    # ** unpacks the dict, so this is the same as cafes=..., cuisines=..., etc.
    return render_template("cafes.html", **filter_cafes())


@app.route("/map")
def map_page():
    data = filter_cafes()

    # the map's javascript needs the cafes as plain data (JSON), not html.
    # only cafes with coordinates can go on the map - the rest are listed under it
    pins = [
        {
            "id": c["id"],
            "name": c["name"],
            "where": f"{c['address']}, {c['area']}",
            "lat": c["lat"],
            "lng": c["lng"],
            "palette": c["palette"].split(","),
            "rating": round(c["avg_rating"], 1) if c["avg_rating"] else None,
            "url": url_for("cafe_page", cafe_id=c["id"]),
        }
        for c in data["cafes"] if c["lat"] is not None
    ]
    not_on_map = [c for c in data["cafes"] if c["lat"] is None]

    return render_template("map.html", pins=pins, not_on_map=not_on_map, **data)


@app.route("/geocode")
@login_required
def geocode():
    # the "find on map" button on the cafe form calls this with ?q=address.
    # we do the lookup here on the server (not in the browser) so we can set
    # the User-Agent openstreetmap asks for.
    spot = find_address(request.args.get("q", "")[:200])
    if spot is None:
        return {"error": "Couldn't find that address - try adding more detail, or drag the pin yourself."}, 404
    return {"lat": spot[0], "lng": spot[1]}


@app.route("/cafe/<int:cafe_id>")
def cafe_page(cafe_id):
    con = db.get_db()
    cafe = con.execute(CAFE_SELECT + " WHERE cafes.id = ? GROUP BY cafes.id", (cafe_id,)).fetchone()
    if cafe is None:
        abort(404)

    # besides the comment itself, work out 3 extra things for each one:
    #   report_count   - how many people reported it
    #   reported_by_me - did *you* already report it
    #   hidden_by_me   - did *you* hide it
    # the (SELECT ...) bits inside the SELECT are "subqueries" - they run once per comment
    comments = con.execute(
        """SELECT comments.*,
                  users.username AS author,
                  users.avatar   AS author_avatar,
                  (SELECT COUNT(*) FROM reports r WHERE r.comment_id = comments.id) AS report_count,
                  EXISTS (SELECT 1 FROM reports r
                          WHERE r.comment_id = comments.id AND r.user_id = ?) AS reported_by_me,
                  EXISTS (SELECT 1 FROM hidden_comments h
                          WHERE h.comment_id = comments.id AND h.user_id = ?) AS hidden_by_me
           FROM comments
           LEFT JOIN users ON users.id = comments.user_id
           WHERE cafe_id = ?
           ORDER BY created_at DESC, comments.id DESC""",
        (my_id(), my_id(), cafe_id),
    ).fetchall()

    # all the photos people posted, for the gallery strip at the top.
    # skip photos from comments that are hidden (by you, or by too many reports)
    photos = [
        c["photo"] for c in comments
        if c["photo"] and not c["hidden_by_me"] and c["report_count"] < db.REPORT_LIMIT
    ]

    # admins get a "merge into..." dropdown: cafes that look like this one first
    merge_similar, merge_others = [], []
    if g.user and g.user["is_admin"]:
        similar_ids = {m["id"] for m in find_similar_cafes(cafe["name"], cafe["lat"], cafe["lng"], skip_id=cafe_id)}
        for c in con.execute("SELECT id, name, area FROM cafes WHERE id != ? ORDER BY name", (cafe_id,)):
            (merge_similar if c["id"] in similar_ids else merge_others).append(c)

    return render_template(
        "cafe.html", cafe=cafe, comments=comments, photos=photos,
        report_limit=db.REPORT_LIMIT, report_reasons=REPORT_REASONS,
        cafe_report_reasons=CAFE_REPORT_REASONS,
        merge_similar=merge_similar, merge_others=merge_others,
    )


@app.route("/cafe/<int:cafe_id>/comment", methods=["POST"])
@login_required
def add_comment(cafe_id):
    error = create_comment(cafe_id)
    if error:
        flash(error)
        return redirect(url_for("cafe_page", cafe_id=cafe_id) + "#write")

    flash("Posted! Thanks for sharing your oshikatsu ♡")
    # redirect after a POST so refreshing the page doesn't post it twice
    return redirect(url_for("cafe_page", cafe_id=cafe_id) + "#comments")


@app.route("/post", methods=["GET", "POST"])
@login_required
def new_post():
    # the yellow + button on the feed. same as commenting on a cafe page,
    # except you choose the cafe from a dropdown
    cafe_list = db.get_db().execute("SELECT id, name, area FROM cafes ORDER BY name").fetchall()

    if request.method == "GET":
        # ?cafe=3 pre-selects a cafe
        return render_template("new_post.html", cafes=cafe_list, form={"cafe_id": request.args.get("cafe", "")})

    try:
        cafe_id = int(request.form.get("cafe_id", 0))
    except ValueError:
        cafe_id = 0

    if not request.files.get("photo") or not request.files["photo"].filename:
        flash("Posts need a photo! (or leave a comment without one on the cafe's page)")
        return render_template("new_post.html", cafes=cafe_list, form=request.form)

    error = create_comment(cafe_id)
    if error:
        flash(error)
        return render_template("new_post.html", cafes=cafe_list, form=request.form)

    flash("Posted ♡")
    return redirect(url_for("feed"))


def find_similar_cafes(name, lat=None, lng=None, skip_id=None):
    """
    Cafes that might be the same place as the one being added:
      - the name is (nearly) the same, anywhere   e.g. "nanas" -> Nana's Green Tea
      - or it's within 30m of the pin              e.g. two names for one shop
    each result gets a "why" so the page can say why it's suggesting it.
    """
    matches = []
    for c in db.get_db().execute("SELECT * FROM cafes").fetchall():
        if c["id"] == skip_id:
            continue
        why = None
        if names_match(name, c["name"]):
            why = "similar name"
        if lat is not None and c["lat"] is not None:
            metres = metres_apart(lat, lng, c["lat"], c["lng"])
            if metres <= 30 or (why and metres <= 1000):
                why = f"{'similar name, ' if why else ''}{round(metres)}m away"
        if why:
            matches.append({"id": c["id"], "name": c["name"], "where": f"{c['address']}, {c['area']}",
                            "palette": c["palette"].split(","), "why": why,
                            "url": url_for("cafe_page", cafe_id=c["id"])})
    return matches[:5]


@app.route("/cafes/similar")
@login_required
def similar_cafes():
    # the add-cafe form calls this while you type, to show "already on here?"
    def number(key):
        try:
            return float(request.args[key])
        except (KeyError, ValueError):
            return None

    name = request.args.get("name", "").strip()[:80]
    lat, lng = number("lat"), number("lng")
    if len(name) < 3 and lat is None:
        return {"matches": []}
    if lng is None:
        lat = None
    return {"matches": find_similar_cafes(name, lat, lng)}


@app.route("/cafe/<int:cafe_id>/report", methods=["POST"])
@login_required
def report_cafe(cafe_id):
    con = db.get_db()
    if con.execute("SELECT 1 FROM cafes WHERE id = ?", (cafe_id,)).fetchone() is None:
        abort(404)

    reason = request.form.get("reason", "")
    if reason not in CAFE_REPORT_REASONS:
        reason = "other"
    note = request.form.get("note", "").strip()[:300]

    # one open report per person per cafe is enough
    already = con.execute(
        "SELECT 1 FROM cafe_reports WHERE cafe_id = ? AND user_id = ? AND resolved = 0", (cafe_id, g.user["id"])
    ).fetchone()
    if not already:
        con.execute("INSERT INTO cafe_reports (cafe_id, user_id, reason, note) VALUES (?, ?, ?, ?)",
                    (cafe_id, g.user["id"], reason, note))
        con.commit()

    flash("Thanks! An admin will take a look.")
    return redirect(url_for("cafe_page", cafe_id=cafe_id))


CAFE_REPORT_REASONS = ["duplicate of another café", "wrong info / wrong pin", "closed down", "not a real café", "other"]

HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


def read_cafe_form():
    """
    Reads the add/edit cafe form. Returns (fields, error).
    fields is a dict ready to save to the database.
    """
    f = request.form
    fields = {
        "name": f.get("name", "").strip()[:80],
        "address": f.get("address", "").strip()[:120],
        "area": f.get("area", "").strip()[:40],
        "tags": f.get("tags", "").strip()[:120],
        "price": f.get("price", "").strip()[:12],
        "website": clean_website(f.get("website")),
        "instagram": clean_handle(f.get("instagram")),
        "tiktok": clean_handle(f.get("tiktok")),
    }

    # the 3 colour pickers. only accept real colour codes like "#8dbf3a",
    # because these go straight into style="background: ..." in the html
    palette = [f.get(f"colour{i}", "") for i in range(1, 4)]
    fields["palette"] = ",".join(c for c in palette if HEX_COLOUR.match(c))

    # the map pin: hidden lat/lng inputs that the form's map fills in
    try:
        lat, lng = float(f.get("lat", "")), float(f.get("lng", ""))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
    except ValueError:
        lat = lng = None

    if not fields["name"] or not fields["address"] or not fields["area"]:
        return fields, "Name, street and area are needed."
    if not fields["palette"]:
        return fields, "Pick at least one palette colour."
    if f.get("website", "").strip() and not fields["website"]:
        return fields, "That website link doesn't look right."

    # no pin placed? try to find the address automatically
    if lat is None:
        spot = find_address(f"{fields['address']}, {fields['area']}")
        if spot:
            lat, lng = spot
            flash("We placed the map pin from the address - check it's in the right spot!")
    fields["lat"], fields["lng"] = lat, lng

    return fields, None


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_cafe():
    if request.method == "GET":
        return render_template("cafe_form.html", cafe=None)

    fields, error = read_cafe_form()
    if error:
        flash(error)
        return render_template("cafe_form.html", cafe=None, form=request.form)

    # duplicate check: if it looks like a cafe we already have, show the
    # matches and ask first. "confirm_new" is the hidden box the
    # "no, it's a different place" button sends, so the 2nd try goes through.
    if not request.form.get("confirm_new"):
        matches = find_similar_cafes(fields["name"], fields["lat"], fields["lng"])
        if matches:
            return render_template("cafe_form.html", cafe=None, form=request.form, matches=matches)

    fields["cover"] = save_photo(request.files.get("cover"))
    fields["added_by"] = g.user["id"]

    # build "INSERT INTO cafes (name, address, ...) VALUES (?, ?, ...)" from the dict.
    # the column names come from our own dict above, never from the user, so this is safe
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    con = db.get_db()
    cur = con.execute(f"INSERT INTO cafes ({cols}) VALUES ({marks})", list(fields.values()))
    con.commit()

    # cur.lastrowid = the id sqlite just gave the new cafe
    return redirect(url_for("cafe_page", cafe_id=cur.lastrowid))


@app.route("/cafe/<int:cafe_id>/edit", methods=["GET", "POST"])
@login_required
def edit_cafe(cafe_id):
    con = db.get_db()
    cafe = con.execute("SELECT * FROM cafes WHERE id = ?", (cafe_id,)).fetchone()
    if cafe is None:
        abort(404)

    # only the person who added the cafe (or an admin) can edit it.
    # (cafe.html hides the edit button from everyone else, but that's just
    # looks - this check is what actually stops someone typing the url)
    if cafe["added_by"] != g.user["id"] and not g.user["is_admin"]:
        abort(403)  # 403 = "forbidden"

    if request.method == "GET":
        return render_template("cafe_form.html", cafe=cafe)

    fields, error = read_cafe_form()
    if error:
        flash(error)
        return render_template("cafe_form.html", cafe=cafe, form=request.form)

    # new cover photo uploaded? swap it in and delete the old file
    new_cover = save_photo(request.files.get("cover"))
    if new_cover:
        delete_photo(cafe["cover"])
        fields["cover"] = new_cover

    # builds "UPDATE cafes SET name = ?, address = ?, ... WHERE id = ?"
    sets = ", ".join(f"{col} = ?" for col in fields)
    con.execute(f"UPDATE cafes SET {sets} WHERE id = ?", [*fields.values(), cafe_id])
    con.commit()

    flash("Cafe updated!")
    return redirect(url_for("cafe_page", cafe_id=cafe_id))


# ---- profiles + following ----

@app.route("/u/<username>")
def profile(username):
    con = db.get_db()
    user = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        abort(404)

    stats = con.execute(
        """SELECT (SELECT COUNT(*) FROM follows WHERE followee_id = :id) AS followers,
                  (SELECT COUNT(*) FROM follows WHERE follower_id = :id) AS following,
                  (SELECT COUNT(*) FROM comments WHERE user_id = :id)    AS reviews""",
        {"id": user["id"]},  # :id placeholders let us use the same value 3 times
    ).fetchone()

    is_following = con.execute(
        "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?", (my_id(), user["id"])
    ).fetchone() is not None

    posts = get_posts("comments.user_id = ?", (user["id"],), limit=60)

    return render_template("profile.html", profile=user, stats=stats,
                           is_following=is_following, posts=posts)


@app.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile():
    oshis = request.form.get("oshis", "").strip()[:200]
    bio = request.form.get("bio", "").strip()[:300]

    # profile picture: keep the old one unless a new one was uploaded,
    # or the "remove" box was ticked
    avatar = g.user["avatar"]
    new_photo = save_photo(request.files.get("avatar"))
    if new_photo or request.form.get("remove_avatar"):
        delete_photo(avatar)       # throw away the old file so uploads/ doesn't fill up
        avatar = new_photo         # None if they only ticked "remove"
    elif request.files.get("avatar") and request.files["avatar"].filename:
        flash("That file isn't a picture we can use (png, jpg, gif or webp).")

    con = db.get_db()
    con.execute("UPDATE users SET oshis = ?, bio = ?, avatar = ? WHERE id = ?",
                (oshis, bio, avatar, g.user["id"]))
    con.commit()
    flash("Profile saved!")
    return redirect(url_for("profile", username=g.user["username"]))


@app.route("/u/<username>/follow", methods=["POST"])
@login_required
def toggle_follow(username):
    con = db.get_db()
    user = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        abort(404)
    if user["id"] == g.user["id"]:
        return redirect(url_for("profile", username=username))  # can't follow yourself

    # follow if not following, unfollow if already following
    deleted = con.execute(
        "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?", (g.user["id"], user["id"])
    ).rowcount
    if not deleted:
        con.execute("INSERT INTO follows (follower_id, followee_id) VALUES (?, ?)", (g.user["id"], user["id"]))
    con.commit()
    return redirect(request.referrer or url_for("profile", username=username))


# ---- like / delete / hide / report ----
# all of these are POST only. if delete worked with a normal link (GET),
# a browser pre-loading links or someone sending you a sneaky url could
# delete things without you clicking anything.

def get_comment_or_404(comment_id):
    comment = db.get_db().execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if comment is None:
        abort(404)
    return comment


def go_back(comment):
    # send people back to whichever page they clicked from (feed, profile...)
    return redirect(request.referrer or url_for("cafe_page", cafe_id=comment["cafe_id"]))


@app.route("/comment/<int:comment_id>/like", methods=["POST"])
@login_required
def toggle_like(comment_id):
    comment = get_comment_or_404(comment_id)
    con = db.get_db()
    removed = con.execute(
        "DELETE FROM likes WHERE user_id = ? AND comment_id = ?", (g.user["id"], comment_id)
    ).rowcount
    if not removed:
        con.execute("INSERT INTO likes (user_id, comment_id) VALUES (?, ?)", (g.user["id"], comment_id))
    con.commit()

    # normally the like button is sent by javascript (see base.html), which
    # just wants to know "liked or not, and how many likes now?" so it can
    # update the heart without reloading the page. we answer with JSON
    # (flask turns a python dict into JSON automatically).
    if request.headers.get("X-Requested-With") == "fetch":
        count = con.execute("SELECT COUNT(*) FROM likes WHERE comment_id = ?", (comment_id,)).fetchone()[0]
        return {"liked": not removed, "count": count}

    # if javascript is off, the form submits normally - go back to the same
    # page and "#post-12" scrolls to the post you liked
    page = (request.referrer or url_for("feed")).split("#")[0]
    return redirect(f"{page}#post-{comment_id}")


@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    comment = get_comment_or_404(comment_id)

    # the important check: only the person who wrote it (or an admin) can delete it.
    # hiding the button in the html isn't enough - anyone can send a POST by hand
    mine = comment["user_id"] == g.user["id"]
    if not mine and not g.user["is_admin"]:
        abort(403)  # 403 = "forbidden"

    remove_comments("id = ?", (comment_id,))

    # a comment with a photo shows up as a "post" in the feed, so call it that
    kind = "post" if comment["photo"] else "comment"
    flash(f"Your {kind} was deleted." if mine else f"{kind.capitalize()} removed (admin).")
    return redirect(request.referrer or url_for("cafe_page", cafe_id=comment["cafe_id"]) + "#comments")


@app.route("/comment/<int:comment_id>/hide", methods=["POST"])
@login_required
def hide_comment(comment_id):
    comment = get_comment_or_404(comment_id)
    con = db.get_db()
    # "INSERT OR IGNORE" = if you already hid it, just do nothing instead of erroring
    con.execute("INSERT OR IGNORE INTO hidden_comments (comment_id, user_id) VALUES (?, ?)",
                (comment_id, g.user["id"]))
    con.commit()
    return go_back(comment)


@app.route("/comment/<int:comment_id>/unhide", methods=["POST"])
@login_required
def unhide_comment(comment_id):
    comment = get_comment_or_404(comment_id)
    con = db.get_db()
    con.execute("DELETE FROM hidden_comments WHERE comment_id = ? AND user_id = ?", (comment_id, g.user["id"]))
    con.commit()
    return go_back(comment)


@app.route("/comment/<int:comment_id>/report", methods=["POST"])
@login_required
def report_comment(comment_id):
    comment = get_comment_or_404(comment_id)

    if comment["user_id"] == g.user["id"]:
        flash("You can't report your own comment - just delete it instead.")
        return go_back(comment)

    reason = request.form.get("reason", "")
    if reason not in REPORT_REASONS:
        reason = "other"

    con = db.get_db()
    con.execute("INSERT OR IGNORE INTO reports (comment_id, user_id, reason) VALUES (?, ?, ?)",
                (comment_id, g.user["id"], reason))
    # reporting also hides it for you straight away - you don't want to keep seeing it
    con.execute("INSERT OR IGNORE INTO hidden_comments (comment_id, user_id) VALUES (?, ?)",
                (comment_id, g.user["id"]))
    con.commit()

    flash("Thanks, the comment was reported and hidden for you.")
    return go_back(comment)


@app.errorhandler(413)
def too_big(e):
    flash("That photo is too big (max 8MB).")
    return redirect(request.referrer or url_for("home"))


# make sure the database + uploads folder exist. this is out here (not inside
# the if below) so it also runs when the app is started by tests or a server.
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
db.init_db()

if __name__ == "__main__":
    # debug=True reloads the server when you save a file + shows errors in
    # the browser. turn it off if you ever put this online for real.
    app.run(debug=True)
