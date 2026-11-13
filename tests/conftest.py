# tests/conftest.py
# shared setup for all the tests. pytest loads this file automatically.
#
# run every test with:   .venv\Scripts\python -m pytest
# just one file:         .venv\Scripts\python -m pytest tests/test_admin.py
# show each test name:   .venv\Scripts\python -m pytest -v
#
# every test gets:
#   - a brand new empty database (with the 4 starter cafes) in a temp folder
#   - its own temp uploads folder
#   - fake map lookups, so tests never need the internet
# so tests can't touch your real cafe.db or photos, and can't affect each other.

import io
import os
import sys
import tempfile

import pytest

# point the app at a throwaway database BEFORE app.py is imported
# (app.py sets up the database as soon as it's imported)
os.environ["OSHI_DB"] = os.path.join(tempfile.mkdtemp(), "import.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as cafe_app  # noqa: E402  (has to come after the lines above)
import db  # noqa: E402


# where the fake map lookup "finds" things. anything else -> not found
FAKE_PLACES = {
    "katherine pl": (-37.82023, 144.95660),
    "swanston st": (-37.81549, 144.96655),
}


def fake_find_address(text):
    text = text.lower()
    for street, spot in FAKE_PLACES.items():
        if street in text:
            return spot
    return None


@pytest.fixture(autouse=True)
def fresh_site(tmp_path, monkeypatch):
    """runs before every test (autouse) - new database, uploads folder, fake maps"""
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "test.db"))
    db.init_db()

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setitem(cafe_app.app.config, "UPLOAD_FOLDER", str(uploads))

    # app.py did "from places import find_address", so swap the copy inside app.py
    monkeypatch.setattr(cafe_app, "find_address", fake_find_address)
    return uploads


@pytest.fixture
def uploads(fresh_site):
    """the temp uploads folder, for tests that check photo files"""
    return fresh_site


class Browser:
    """
    a pretend browser for one person. wraps flask's test client so tests can say
        amy.post("/cafe/1/save", {"saved": "1"})
    without worrying about the csrf token every time.
    """

    def __init__(self):
        self.client = cafe_app.app.test_client()

    def csrf(self):
        self.client.get("/home")  # any page - makes sure the session has a token
        with self.client.session_transaction() as s:
            return s["csrf"]

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def page(self, url):
        """the html of a page as text"""
        return self.client.get(url).data.decode()

    def post(self, url, data=None, fetch=False, **kw):
        data = dict(data or {})
        data["csrf"] = self.csrf()
        if fetch:  # pretend it came from the javascript in base.html
            kw.setdefault("headers", {})["X-Requested-With"] = "fetch"
        if any(isinstance(v, tuple) for v in data.values()):
            kw["content_type"] = "multipart/form-data"  # needed for file uploads
        return self.client.post(url, data=data, **kw)

    def signup(self, username, password="secret1", **extra):
        return self.post("/signup", {"username": username, "password": password, "password2": password, **extra})

    def make_post(self, body, cafe_id=1, rating=5, oshi="", filename="photo.png"):
        """a post = a comment with a photo"""
        return self.post("/post", {"cafe_id": str(cafe_id), "rating": str(rating), "body": body,
                                   "oshi": oshi, "photo": photo(filename)})


def photo(name="photo.png"):
    """a tiny fake image upload"""
    return (io.BytesIO(b"\x89PNG\r\n\x1a\n fake image"), name)


@pytest.fixture
def browser():
    """a logged-out visitor"""
    return Browser()


@pytest.fixture
def amy():
    b = Browser()
    b.signup("amy")
    return b


@pytest.fixture
def ben():
    b = Browser()
    b.signup("ben")
    return b


@pytest.fixture
def admin():
    b = Browser()
    b.signup("boss")
    db.set_admin("boss")
    return b


def one(sql, *params):
    """run a query on the test database and return the first value"""
    con = db.sqlite3.connect(db.DB_FILE)
    try:
        row = con.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        con.close()
