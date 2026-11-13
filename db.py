# db.py
# everything to do with the database lives here so app.py stays readable.
# we're using sqlite because it's built into python - the whole database
# is just one file (cafe.db) that gets created the first time you run the app.
#
# want to look inside it? download "DB Browser for SQLite" (free) and open
# cafe.db - you can see every table and row like a spreadsheet.

import os
import sqlite3
from flask import g

# keep cafe.db next to this file, no matter which folder you run python from
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cafe.db")

# once a comment gets this many reports, it's hidden for everyone
REPORT_LIMIT = 3


def get_db():
    # NOTE: `g` is flask's "per request" storage. we open one connection per
    # request and reuse it, instead of reconnecting every time we run a query.
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        # row_factory lets us do row["name"] instead of row[1]
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# the tables and how they connect:
#
#   users ──< comments >── cafes        a user writes many comments,
#     │          │                      a cafe has many comments
#     │          ├──< likes             (a "comment" with a photo is what
#     │          ├──< reports            shows up as a post in the feed)
#     │          └──< hidden_comments
#     └──< follows (user follows user)
#
# "──<" means "one to many". the arrows are the *_id columns.
#
# palette is stored as a plain string like "#8dbf3a,#d8b48c,#ffffff"
# (splitting it into 3 columns would work too, but this way a cafe can
# have more or fewer colours later without changing the table)
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    oshis         TEXT,             -- "Kaito, Seiji" - used for the "Your Oshis" tab
    bio           TEXT,
    avatar        TEXT,             -- profile picture filename in static/uploads (or NULL)
    is_admin      INTEGER DEFAULT 0, -- 1 = admin (can fix/merge/delete any cafe, see /admin)
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- "report cafe" (wrong info, duplicate, closed...). shows up on the admin page.
-- resolved = 1 once an admin has dealt with it
CREATE TABLE IF NOT EXISTS cafe_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cafe_id    INTEGER NOT NULL REFERENCES cafes(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    reason     TEXT NOT NULL,
    note       TEXT,
    resolved   INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cafes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    address    TEXT NOT NULL,
    area       TEXT NOT NULL,
    tags       TEXT,
    price      TEXT,
    cover      TEXT,
    palette    TEXT NOT NULL,
    lat        REAL,                -- latitude  (e.g. -37.81) - where the pin goes on the map
    lng        REAL,                -- longitude (e.g. 144.96). NULL = not on the map yet
    website    TEXT,                -- full link, e.g. https://example.com
    instagram  TEXT,                -- just the handle, no @ (e.g. nanasgreenteamelb)
    tiktok     TEXT,                -- same, just the handle
    added_by   INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cafe_id    INTEGER NOT NULL REFERENCES cafes(id),
    user_id    INTEGER REFERENCES users(id),
    username   TEXT NOT NULL,    -- copied from users so old comments still show a name
    oshi       TEXT,
    rating     INTEGER NOT NULL,
    body       TEXT NOT NULL,
    photo      TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- follower_id follows followee_id
CREATE TABLE IF NOT EXISTS follows (
    follower_id INTEGER NOT NULL REFERENCES users(id),
    followee_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (follower_id, followee_id)
);

-- the heart on cafe cards = "save this cafe" (shows on the Saved page)
CREATE TABLE IF NOT EXISTS saved_cafes (
    user_id    INTEGER NOT NULL REFERENCES users(id),
    cafe_id    INTEGER NOT NULL REFERENCES cafes(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, cafe_id)
);

-- the heart button on feed posts
CREATE TABLE IF NOT EXISTS likes (
    user_id    INTEGER NOT NULL REFERENCES users(id),
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    PRIMARY KEY (user_id, comment_id)
);

-- one row each time someone reports a comment.
-- UNIQUE stops the same person reporting the same comment twice
CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    reason     TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (comment_id, user_id)
);

-- "hide this comment for me" - only affects the person who hid it
CREATE TABLE IF NOT EXISTS hidden_comments (
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (comment_id, user_id)
);
"""

# a few cafes from the mockup so the pages aren't empty on first run.
# no cover photos or social links yet - add them with the "edit" button on each
# cafe's page. coordinates came from OpenStreetMap's address search.
# NOTE: Wooss isn't on OpenStreetMap, so its pin is just "somewhere on La Trobe St" -
# drag it to the right spot on its edit page.
#   (name, street, area, tags, price, palette, lat, lng)
STARTER_CAFES = [
    ("Nana's Green Tea", "Swanston St", "CBD", "Café, Japanese", "$-$$", "#8dbf3a,#d8b48c,#ffffff", -37.80712, 144.96246),
    ("Wooss", "La Trobe St", "CBD", "Café, Japanese", "$-$$", "#cfc58a,#e0c0a0,#ffffff", -37.80990, 144.96390),
    ("The Butter Room", "Katherine Pl", "CBD", "Café, Korean, Bakery", "$$", "#f5c400,#c08f5a,#ffffff", -37.81994, 144.95654),
    ("AMIRI CAFE", "Lonsdale St", "QV", "Café, Asian, Food", "$$-$$$", "#7a4a2a,#c9a07a,#ffffff", -37.81104, 144.96585),
]


def _columns(con, table):
    return [row[1] for row in con.execute(f"PRAGMA table_info({table})")]


def _upgrade_old_database(con):
    # NOTE: "CREATE TABLE IF NOT EXISTS" never changes a table that already
    # exists. so if cafe.db was made by an older version of this code, the
    # tables are missing the new columns - we add them here by hand.
    if "user_id" not in _columns(con, "comments"):
        con.execute("ALTER TABLE comments ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if "added_by" not in _columns(con, "cafes"):
        con.execute("ALTER TABLE cafes ADD COLUMN added_by INTEGER REFERENCES users(id)")

    # map + social links were added later
    for col, kind in (("lat", "REAL"), ("lng", "REAL"), ("website", "TEXT"),
                      ("instagram", "TEXT"), ("tiktok", "TEXT")):
        if col not in _columns(con, "cafes"):
            con.execute(f"ALTER TABLE cafes ADD COLUMN {col} {kind}")

    # give the starter cafes their map pins if they don't have one yet
    for name, *_, lat, lng in STARTER_CAFES:
        con.execute("UPDATE cafes SET lat = ?, lng = ? WHERE name = ? AND lat IS NULL", (lat, lng, name))

    # the old reports/hidden tables were keyed by browser cookie, not by
    # account. they can't be converted, so start them fresh.
    if "reporter" in _columns(con, "reports"):
        con.execute("DROP TABLE reports")
    if "visitor" in _columns(con, "hidden_comments"):
        con.execute("DROP TABLE hidden_comments")


def init_db():
    con = sqlite3.connect(DB_FILE)

    # only run the upgrade if there's an existing comments table to upgrade
    if _columns(con, "comments"):
        _upgrade_old_database(con)

    # profile pictures were added after accounts, so older users tables need the column
    user_columns = _columns(con, "users")
    if user_columns and "avatar" not in user_columns:
        con.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
    if user_columns and "is_admin" not in user_columns:
        con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

    con.executescript(SCHEMA)

    # only add the starter cafes if the table is empty,
    # otherwise we'd get duplicates every time the app restarts
    if con.execute("SELECT COUNT(*) FROM cafes").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO cafes (name, address, area, tags, price, palette, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            STARTER_CAFES,
        )
    con.commit()
    con.close()


def set_admin(username, admin=True):
    """Make someone an admin (or take it away). Returns False if there's no such user."""
    con = sqlite3.connect(DB_FILE)
    changed = con.execute("UPDATE users SET is_admin = ? WHERE username = ? COLLATE NOCASE",
                          (1 if admin else 0, username)).rowcount
    con.commit()
    con.close()
    return changed > 0


# there's no "make admin" button on the site on purpose - otherwise someone
# could find a way to make themselves admin. you do it from the terminal:
#
#     .venv\Scripts\python db.py make-admin Choi_Mino
#     .venv\Scripts\python db.py remove-admin someone
#
if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] in ("make-admin", "remove-admin"):
        init_db()  # makes sure the is_admin column exists
        name = sys.argv[2]
        if set_admin(name, sys.argv[1] == "make-admin"):
            print(f"done - {name} is {'now' if sys.argv[1] == 'make-admin' else 'no longer'} an admin")
        else:
            print(f"no user called {name}")
    else:
        print("usage: python db.py make-admin USERNAME   (or remove-admin)")
