# tests for accounts: sign up, log in/out, change password, delete account, csrf

import db
from conftest import Browser, one, photo


def test_signup_logs_you_in(browser):
    r = browser.signup("mina", oshis="Hoshi, Seiji")
    assert r.status_code == 302 and r.location == "/home"
    assert "/account/password" in browser.page("/u/mina")   # only shown on your own profile


def test_password_is_hashed_not_saved(browser):
    browser.signup("mina", password="hunter22")
    saved = one("SELECT password_hash FROM users WHERE username = 'mina'")
    assert "hunter22" not in saved
    assert saved.startswith(("scrypt", "pbkdf2"))


def test_signup_rules(browser):
    assert "taken" not in browser.signup("mina").data.decode()
    other = Browser()
    assert "taken" in other.signup("MINA").data.decode()                       # same name, different case
    assert "at least" in other.signup("bob", password="123").data.decode()      # too short
    assert "3-20 letters" in other.signup("a b!").data.decode()                 # bad characters
    r = other.post("/signup", {"username": "bob", "password": "secret1", "password2": "different"})
    assert "don&#39;t match" in r.data.decode()


def test_login_and_logout(amy):
    r = amy.post("/logout")
    assert r.location == "/"
    assert "Logged out" in amy.page("/")                                # message shows on the landing page
    assert "/login" in amy.get("/saved").location                       # logged out now

    assert "Wrong username" in amy.post("/login", {"username": "amy", "password": "nope"}).data.decode()
    r = amy.post("/login", {"username": "AMY", "password": "secret1", "next": "/feed"})
    assert r.location == "/feed"                                        # sends you back where you were


def test_login_never_redirects_to_other_sites(amy):
    amy.post("/logout")
    r = amy.post("/login", {"username": "amy", "password": "secret1", "next": "//evil.com"})
    assert r.location == "/home"


def test_forms_without_csrf_token_are_rejected(browser):
    r = browser.client.post("/login", data={"username": "x", "password": "y"})
    assert r.status_code == 400


def test_landing_skips_to_home_when_logged_in(amy, browser):
    assert amy.get("/").status_code == 302
    assert browser.get("/").status_code == 200


def test_change_password(amy):
    def change(current, new, new2=None):
        return amy.post("/account/password", {"current": current, "new": new, "new2": new2 or new})

    assert "current password is wrong" in change("nope", "newpass1").data.decode()
    assert "don&#39;t match" in change("secret1", "newpass1", "newpass2").data.decode()
    assert "at least" in change("secret1", "123").data.decode()
    assert "same as your current" in change("secret1", "secret1").data.decode()

    r = change("secret1", "newpass1")
    assert r.location == "/u/amy"
    assert "/account/password" in amy.page("/u/amy")                    # still logged in

    other = Browser()
    assert "Wrong username" in other.post("/login", {"username": "amy", "password": "secret1"}).data.decode()
    assert other.post("/login", {"username": "amy", "password": "newpass1"}).status_code == 302


def test_delete_account_needs_password_and_tick(amy):
    assert "NOT deleted" in amy.post("/account/delete", {"password": "nope", "confirm": "1"}).data.decode()
    assert "Tick the box" in amy.post("/account/delete", {"password": "secret1"}).data.decode()
    assert one("SELECT COUNT(*) FROM users WHERE username = 'amy'") == 1


def test_delete_account_removes_everything(amy, ben, uploads):
    amy.post("/profile/edit", {"oshis": "", "bio": "", "avatar": photo("me.png")})
    amy.make_post("amy post", filename="a.png")
    ben.make_post("ben post", filename="b.png")
    amy_post = one("SELECT id FROM comments WHERE body = 'amy post'")
    ben_post = one("SELECT id FROM comments WHERE body = 'ben post'")
    ben.post(f"/comment/{amy_post}/like", fetch=True)
    amy.post(f"/comment/{ben_post}/like", fetch=True)
    ben.post(f"/comment/{amy_post}/report", {"reason": "spam"})
    amy.post("/u/ben/follow")
    ben.post("/u/amy/follow")
    amy.post("/cafe/2/save", {"saved": "1"}, fetch=True)
    amy.post("/cafe/3/report", {"reason": "closed down"})
    amy.post("/add", {"name": "Amy Cafe", "address": "A St", "area": "CBD", "colour1": "#ff0000",
                      "lat": "-37.86", "lng": "144.90"})
    assert len(list(uploads.iterdir())) == 3

    r = amy.post("/account/delete", {"password": "secret1", "confirm": "1"})
    assert r.location == "/"
    assert "account was deleted" in amy.page("/")

    assert one("SELECT COUNT(*) FROM users WHERE username = 'amy'") == 0
    assert one("SELECT COUNT(*) FROM comments WHERE body = 'amy post'") == 0
    for table in ("likes", "reports", "follows", "saved_cafes", "cafe_reports"):
        assert one(f"SELECT COUNT(*) FROM {table}") == 0, table
    # cafes she added stay (with no owner), other people's posts stay
    assert one("SELECT COUNT(*) FROM cafes WHERE name = 'Amy Cafe' AND added_by IS NULL") == 1
    assert one("SELECT COUNT(*) FROM comments WHERE body = 'ben post'") == 1
    # her photo + profile picture deleted, ben's photo kept
    assert [f.name.endswith("b.png") for f in uploads.iterdir()] == [True]
    # name is free again
    assert Browser().signup("amy").status_code == 302


def test_make_admin_command():
    # same function "python db.py make-admin NAME" uses
    Browser().signup("mina")
    assert db.set_admin("mina")
    assert not db.set_admin("nobody")
    assert one("SELECT is_admin FROM users WHERE username = 'mina'") == 1
