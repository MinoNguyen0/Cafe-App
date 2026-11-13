# tests for the admin role: /admin, merging + deleting cafes, removing comments

from conftest import Browser, one

DUP = {"name": "Nanas Green Tea", "address": "Swanston St", "area": "CBD",
       "colour1": "#8dbf3a", "lat": "-37.80712", "lng": "144.96246", "confirm_new": "1"}


def test_only_admins_get_in(amy, admin, browser):
    assert amy.get("/admin").status_code == 403
    assert "/login" in browser.get("/admin").location
    assert admin.get("/admin").status_code == 200

    assert "admin page" in admin.page("/u/boss")
    assert "admin page" not in amy.page("/u/amy")
    assert "admin-box" in admin.page("/cafe/1")
    assert "admin-box" not in amy.page("/cafe/1")


def test_non_admins_cant_use_admin_actions(amy):
    assert amy.post("/admin/cafe/1/delete").status_code == 403
    assert amy.post("/admin/cafe/1/merge", {"into": "2"}).status_code == 403
    assert amy.post("/admin/cafe/1/resolve").status_code == 403


def test_admin_can_edit_any_cafe(amy, ben, admin):
    amy.post("/add", dict(DUP, name="Amy Spot", lat="-37.86", lng="144.90"))
    cafe_id = one("SELECT id FROM cafes WHERE name = 'Amy Spot'")
    assert admin.get(f"/cafe/{cafe_id}/edit").status_code == 200
    assert admin.get("/cafe/1/edit").status_code == 200              # starter cafes too
    assert ben.get(f"/cafe/{cafe_id}/edit").status_code == 403


def test_reports_show_on_admin_page(amy, ben, admin):
    ben.post("/cafe/2/report", {"reason": "wrong info / wrong pin", "note": "pin is a block off"})
    html = admin.page("/admin")
    assert "Wooss" in html and "pin is a block off" in html

    admin.post("/admin/cafe/2/resolve")
    assert "no reported cafés" in admin.page("/admin")


def test_merge_duplicate(amy, ben, admin, uploads):
    amy.post("/add", DUP)
    dup_id = one("SELECT id FROM cafes WHERE name = 'Nanas Green Tea'")
    ben.make_post("on the copy", cafe_id=dup_id)
    post_id = one("SELECT id FROM comments")
    amy.post(f"/comment/{post_id}/like", fetch=True)
    ben.post(f"/cafe/{dup_id}/save", {"saved": "1"}, fetch=True)
    ben.post("/cafe/1/save", {"saved": "1"}, fetch=True)              # saved both
    ben.post(f"/cafe/{dup_id}/report", {"reason": "duplicate of another café"})

    # the real cafe is listed first under "looks similar"
    html = admin.page(f"/cafe/{dup_id}")
    assert html.index('label="looks similar"') < html.index("Nana&#39;s Green Tea") < html.index('label="all cafés"')

    r = admin.post(f"/admin/cafe/{dup_id}/merge", {"into": "1"})
    assert r.location == "/cafe/1"
    assert one("SELECT COUNT(*) FROM cafes WHERE id = ?", dup_id) == 0
    assert one("SELECT cafe_id FROM comments WHERE id = ?", post_id) == 1      # post moved
    assert one("SELECT COUNT(*) FROM likes") == 1                             # like kept
    assert len(list(uploads.iterdir())) == 1                                  # photo kept
    assert one("SELECT COUNT(*) FROM saved_cafes") == 1                       # no double save
    assert one("SELECT COUNT(*) FROM cafe_reports") == 0


def test_cant_merge_into_itself(admin):
    admin.post("/admin/cafe/1/merge", {"into": "1"})
    assert one("SELECT COUNT(*) FROM cafes WHERE id = 1") == 1


def test_delete_cafe_takes_everything_with_it(amy, admin, uploads):
    amy.make_post("will vanish", cafe_id=3)
    amy.post("/cafe/3/save", {"saved": "1"}, fetch=True)
    r = admin.post("/admin/cafe/3/delete")
    assert r.status_code == 302
    assert one("SELECT COUNT(*) FROM cafes WHERE id = 3") == 0
    assert one("SELECT COUNT(*) FROM comments") == 0
    assert one("SELECT COUNT(*) FROM saved_cafes") == 0
    assert list(uploads.iterdir()) == []


def test_reported_comments(amy, ben, admin, uploads):
    amy.make_post("borderline post")
    post_id = one("SELECT id FROM comments")
    ben.post(f"/comment/{post_id}/report", {"reason": "spam"})
    assert "borderline post" in admin.page("/admin")

    admin.post(f"/admin/comment/{post_id}/dismiss")                    # "it's fine, keep it"
    assert one("SELECT COUNT(*) FROM reports") == 0
    assert one("SELECT COUNT(*) FROM comments") == 1

    assert "remove (admin)" in admin.page("/cafe/1")
    assert "remove (admin)" not in ben.page("/cafe/1")
    assert ben.post(f"/comment/{post_id}/delete").status_code == 403
    admin.post(f"/comment/{post_id}/delete")
    assert one("SELECT COUNT(*) FROM comments") == 0
    assert list(uploads.iterdir()) == []
