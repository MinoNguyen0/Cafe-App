# tests for posts + comments: posting, the feed, likes, follows, delete/hide/report

from conftest import Browser, one, photo


def test_posting_needs_an_account(browser):
    assert "/login" in browser.get("/post").location
    assert "log in to comment" in browser.page("/cafe/1")


def test_post_shows_in_feed(amy, browser):
    assert amy.make_post("hoshi date!", oshi="Hoshi").location == "/feed"
    assert "hoshi date!" in browser.page("/feed")


def test_post_needs_a_photo(amy):
    r = amy.post("/post", {"cafe_id": "1", "rating": "5", "body": "no photo"})
    assert "need a photo" in r.data.decode()


def test_comment_without_photo(amy):
    amy.post("/cafe/1/comment", {"rating": "4", "body": "nice matcha"})
    assert "nice matcha" in amy.page("/cafe/1")
    assert "nice matcha" not in amy.page("/feed")                     # only photo posts go in the feed
    # a bad rating sends you back to the cafe page with a message
    r = amy.post("/cafe/1/comment", {"rating": "9", "body": "x"})
    assert r.location == "/cafe/1#write"
    assert "Please add" in amy.page("/cafe/1")


def test_rating_is_the_average(amy, ben):
    amy.post("/cafe/1/comment", {"rating": "5", "body": "a"})
    ben.post("/cafe/1/comment", {"rating": "2", "body": "b"})
    assert "3.5 · 2 reviews" in amy.page("/cafe/1")


def test_feed_tabs(ben):
    mina = Browser()
    mina.signup("mina", oshis="Hoshi, Seiji")
    mina.make_post("hoshi date!", oshi="Hoshi")

    assert "hoshi date!" in mina.page("/feed?tab=oshis")
    assert "Add your oshis" in ben.page("/feed?tab=oshis")
    assert "Follow people" in ben.page("/feed?tab=following")
    assert "Log in" in Browser().page("/feed?tab=following")

    ben.post("/u/mina/follow")
    assert "hoshi date!" in ben.page("/feed?tab=following")
    assert "From People You Follow" in ben.page("/home")
    assert "<b>1</b> followers" in ben.page("/u/mina")

    ben.post("/u/mina/follow")                                        # tap again = unfollow
    assert "<b>0</b> followers" in ben.page("/u/mina")


def test_home_page_sections(amy, browser):
    html = browser.page("/home")
    assert html.count("new-tile placeholder") == 3                    # nothing posted yet
    assert "to see posts from people you follow" in html

    amy.make_post("first post")
    assert browser.page("/home").count("new-tile placeholder") == 2


def test_likes(amy, ben):
    amy.make_post("like me")
    post_id = one("SELECT id FROM comments")
    assert ben.post(f"/comment/{post_id}/like", fetch=True).get_json() == {"liked": True, "count": 1}
    assert "like me" in ben.page("/saved?tab=posts")                  # liked posts tab
    assert ben.post(f"/comment/{post_id}/like", fetch=True).get_json() == {"liked": False, "count": 0}


def test_like_needs_an_account(amy, browser):
    amy.make_post("x")
    r = browser.post("/comment/1/like", fetch=True, headers={"Referer": "http://localhost/feed"})
    assert r.status_code == 401
    assert r.get_json() == {"login": "/login?next=/feed"}


def test_delete_own_post(amy, ben, uploads):
    amy.make_post("my post")
    post_id = one("SELECT id FROM comments")
    ben.post(f"/comment/{post_id}/like", fetch=True)

    assert 'class="post-delete"' in amy.page("/feed")
    assert "post-delete" not in ben.page("/feed")
    assert ben.post(f"/comment/{post_id}/delete").status_code == 403

    amy.post(f"/comment/{post_id}/delete")
    assert "Your post was deleted." in amy.page("/feed")
    assert one("SELECT COUNT(*) FROM comments") == 0
    assert one("SELECT COUNT(*) FROM likes") == 0
    assert list(uploads.iterdir()) == []                              # photo file deleted too


def test_hide_and_report_comment(amy, ben):
    amy.make_post("rude post")
    post_id = one("SELECT id FROM comments")

    ben.post(f"/comment/{post_id}/hide")
    assert "you hid a comment from amy" in ben.page("/cafe/1")
    ben.post(f"/comment/{post_id}/unhide")
    assert "rude post" in ben.page("/cafe/1")

    ben.post(f"/comment/{post_id}/report", {"reason": "spam"})
    ben.post(f"/comment/{post_id}/report", {"reason": "spam"})        # twice = once
    assert one("SELECT COUNT(*) FROM reports") == 1
    assert "rude post" not in ben.page("/feed")                       # hidden for the reporter

    # 2 more people report it -> hidden for everyone except amy
    for name in ("cat", "dan"):
        b = Browser()
        b.signup(name)
        b.post(f"/comment/{post_id}/report", {"reason": "offensive / hateful"})
    assert "hidden after being reported" in Browser().page("/cafe/1")
    assert "hidden from others after reports" in amy.page("/cafe/1")


def test_cant_report_own_comment(amy):
    amy.make_post("mine")
    amy.post("/comment/1/report", {"reason": "spam"})
    assert one("SELECT COUNT(*) FROM reports") == 0


def test_profile_picture(amy, uploads):
    amy.post("/profile/edit", {"oshis": "Hoshi", "bio": "hi", "avatar": photo("me.png")})
    avatar = one("SELECT avatar FROM users WHERE username = 'amy'")
    assert avatar and avatar in amy.page("/home")                     # shows in the top bar

    amy.post("/profile/edit", {"oshis": "Hoshi", "bio": "hi", "remove_avatar": "1"})
    assert one("SELECT avatar FROM users WHERE username = 'amy'") is None
    assert list(uploads.iterdir()) == []                              # old picture file deleted
