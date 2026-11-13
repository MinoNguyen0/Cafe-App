# tests that every page loads, and the "are you sure?" popups are where they should be

import pytest

from conftest import one

PUBLIC_PAGES = ["/", "/home", "/feed", "/feed?tab=explore", "/cafes", "/cafes?sort=top",
                "/map", "/cafe/1", "/signup", "/login"]
ACCOUNT_PAGES = ["/saved", "/saved?tab=posts", "/post", "/add", "/account/password",
                 "/account/delete", "/u/amy"]


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_public_pages_load(browser, url):
    assert browser.get(url).status_code == 200


@pytest.mark.parametrize("url", ACCOUNT_PAGES)
def test_account_pages_load(amy, url):
    assert amy.get(url).status_code == 200


@pytest.mark.parametrize("url", ["/saved", "/post", "/add", "/account/password", "/account/delete"])
def test_account_pages_need_login(browser, url):
    assert "/login" in browser.get(url).location


def test_missing_things_are_404(browser):
    assert browser.get("/cafe/999").status_code == 404
    assert browser.get("/u/nobody").status_code == 404


def test_bottom_nav_order(browser):
    html = browser.page("/home")
    spots = [html.index(t) for t in ('title="home"', 'title="feed"', 'id="nav-cafes"',
                                     'title="saved"', 'title="add a cafe"')]
    assert spots == sorted(spots)                                     # map/cafes in the middle


def test_no_emoji_on_the_map(browser):
    html = browser.page("/map")
    assert "📍" not in html and "◎" not in html


@pytest.mark.parametrize("url, text", [
    ("/u/amy", "Log out of @amy?"),
    ("/u/amy", "Save the changes to your profile?"),
    ("/account/password", "Change your password?"),
    ("/account/delete", "Really delete @amy?"),
])
def test_are_you_sure_popups(amy, url, text):
    assert text in amy.page(url).replace("&#39;", "'")


def test_popups_on_posts_and_admin(amy, admin):
    amy.make_post("mine")
    assert "Delete your post at Nana&#39;s Green Tea?" in amy.page("/feed")
    assert "Delete your comment?" in amy.page("/cafe/1")

    html = admin.page("/cafe/1")
    assert "Remove @amy&#39;s post as admin?" in admin.page("/feed")
    assert "Delete “Nana&#39;s Green Tea” and ALL its comments" in html
    assert "Merge “Nana&#39;s Green Tea” into “{target}”?" in html


def test_no_plain_browser_confirm_boxes_left(admin, amy):
    amy.make_post("x")
    for url in ("/cafe/1", "/feed", "/admin", "/u/boss"):
        assert "confirm(" not in admin.page(url).split("<script>")[0]   # only the popup script uses it
    assert one("SELECT COUNT(*) FROM comments") == 1
