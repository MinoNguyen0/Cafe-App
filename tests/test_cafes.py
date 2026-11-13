# tests for cafes: the list + map, filters, adding/editing, links, duplicates, saving

from conftest import one

# a valid "add cafe" form - tests copy it and change bits
NEW_CAFE = {"name": "Brand New Place", "address": "Test St", "area": "CBD",
            "colour1": "#ff0000", "colour2": "#00ff00", "colour3": "#0000ff",
            "lat": "-37.86", "lng": "144.90"}


def count_cards(html):
    return html.count('class="card"')


# ---- list, map, filters ----

def test_cafe_list_and_filters(browser):
    assert count_cards(browser.page("/cafes")) == 4
    assert count_cards(browser.page("/cafes?colour=green")) == 2       # Nana's + Wooss (khaki)
    assert count_cards(browser.page("/cafes?colour=yellow")) == 1      # The Butter Room
    assert count_cards(browser.page("/cafes?area=QV")) == 1
    assert count_cards(browser.page("/cafes?cuisine=Korean")) == 1
    assert count_cards(browser.page("/cafes?q=butter")) == 1


def test_top_rated_stays_on_when_picking_a_filter(browser):
    html = browser.page("/cafes?sort=top")
    assert "Top rated!" in html
    assert 'name="sort" value="top"' in html                         # hidden input carries it along
    assert 'class="filter-link active" href="/cafes"' in html        # tapping again turns it off
    assert 'href="/cafes?sort=top"' in browser.page("/cafes")


def test_list_map_switch_keeps_filters(browser):
    assert 'href="/map?area=CBD&amp;sort=top"' in browser.page("/cafes?area=CBD&sort=top")
    assert 'href="/cafes?area=CBD&amp;sort=top"' in browser.page("/map?area=CBD&sort=top")
    assert "✕ clear" in browser.page("/cafes?area=CBD")
    assert "✕ clear" not in browser.page("/cafes")


def test_map_pins(browser):
    assert browser.page("/map").count('"lat":') == 4
    assert browser.page("/map?colour=yellow").count('"lat":') == 1
    assert "mini-map" in browser.page("/cafe/1")


# ---- adding + editing ----

def test_adding_needs_an_account(browser):
    assert "/login" in browser.get("/add").location


def test_add_cafe(amy):
    r = amy.post("/add", NEW_CAFE)
    assert r.status_code == 302
    assert one("SELECT added_by FROM cafes WHERE name = 'Brand New Place'") == one(
        "SELECT id FROM users WHERE username = 'amy'")


def test_add_without_pin_looks_up_the_address(amy):
    amy.post("/add", dict(NEW_CAFE, name="Laneway Spot", address="Katherine Pl", lat="", lng=""))
    assert one("SELECT lat FROM cafes WHERE name = 'Laneway Spot'") == -37.82023


def test_geocode_button(amy):
    assert amy.get("/geocode?q=Swanston St, CBD").get_json() == {"lat": -37.81549, "lng": 144.96655}
    assert amy.get("/geocode?q=nowhere at all").status_code == 404


def test_bad_form_values_are_rejected(amy):
    r = amy.post("/add", dict(NEW_CAFE, website="javascript:alert(1)"))
    assert "doesn&#39;t look right" in r.data.decode()
    r = amy.post("/add", dict(NEW_CAFE, colour1="red;}body{display:none", colour2="", colour3=""))
    assert "at least one palette colour" in r.data.decode()
    r = amy.post("/add", dict(NEW_CAFE, name=""))
    assert "Name, street and area" in r.data.decode()


def test_links_are_cleaned_and_shown(amy):
    amy.post("/add", dict(NEW_CAFE, website="brandnew.com.au",
                          instagram="https://www.instagram.com/brand.new/", tiktok="@brandnew_tt"))
    cafe_id = one("SELECT id FROM cafes WHERE name = 'Brand New Place'")
    assert one("SELECT website || ' ' || instagram || ' ' || tiktok FROM cafes WHERE id = ?", cafe_id) == \
        "https://brandnew.com.au brand.new brandnew_tt"
    html = amy.page(f"/cafe/{cafe_id}")
    assert "https://www.instagram.com/brand.new/" in html
    assert "tiktok.com/@brandnew_tt" in html
    assert 'href="https://brandnew.com.au"' in html


def test_only_the_owner_can_edit(amy, ben):
    amy.post("/add", NEW_CAFE)
    cafe_id = one("SELECT id FROM cafes WHERE name = 'Brand New Place'")

    assert "edit caf" in amy.page(f"/cafe/{cafe_id}")
    assert "edit caf" not in ben.page(f"/cafe/{cafe_id}")
    assert ben.get(f"/cafe/{cafe_id}/edit").status_code == 403
    assert ben.post(f"/cafe/{cafe_id}/edit", dict(NEW_CAFE, name="hacked")).status_code == 403

    assert amy.post(f"/cafe/{cafe_id}/edit", dict(NEW_CAFE, name="Renamed")).status_code == 302
    assert one("SELECT name FROM cafes WHERE id = ?", cafe_id) == "Renamed"


def test_starter_cafes_have_no_owner(amy):
    assert amy.get("/cafe/1/edit").status_code == 403


# ---- duplicates ----

def test_live_duplicate_check(amy):
    names = lambda url: [m["name"] for m in amy.get(url).get_json()["matches"]]
    assert names("/cafes/similar?name=nanas") == ["Nana's Green Tea"]
    assert names("/cafes/similar?name=Totally New&lat=-37.81104&lng=144.96586") == ["AMIRI CAFE"]  # same spot
    assert names("/cafes/similar?name=Zzz Kitchen&lat=-37.85&lng=144.90") == []


def test_adding_a_duplicate_asks_first(amy):
    dup = dict(NEW_CAFE, name="Nanas Green Tea", lat="-37.80712", lng="144.96246")
    r = amy.post("/add", dup)
    html = r.data.decode()
    assert "is it one of these?" in html and "add it anyway" in html
    assert one("SELECT COUNT(*) FROM cafes") == 4                     # not saved yet

    r = amy.post("/add", dict(dup, confirm_new="1"))                  # "no, it's a different place"
    assert r.status_code == 302
    assert one("SELECT COUNT(*) FROM cafes") == 5


# ---- saved cafes (the hearts) ----

def test_saving_cafes(amy, browser):
    assert amy.post("/cafe/2/save", {"saved": "1"}, fetch=True).get_json() == {"saved": True}
    amy.post("/cafe/4/save", {"saved": "1"}, fetch=True)
    amy.post("/cafe/4/save", {"saved": "1"}, fetch=True)              # twice still = once

    html = amy.page("/saved")
    assert count_cards(html) == 2
    assert html.index("AMIRI") < html.index("Wooss")                  # newest first
    assert amy.page("/cafes").count('class="heart on"') == 2
    assert 'class="save-btn on"' in amy.page("/cafe/2")
    assert browser.page("/cafes").count("heart on") == 0              # hearts are per person

    assert amy.post("/cafe/2/save", {"saved": "0"}, fetch=True).get_json() == {"saved": False}
    assert count_cards(amy.page("/saved")) == 1


def test_saving_needs_an_account(browser):
    r = browser.post("/cafe/1/save", {"saved": "1"}, fetch=True)
    assert r.status_code == 401 and "login" in r.get_json()
    assert "/login" in browser.get("/saved").location


def test_save_missing_cafe(amy):
    assert amy.post("/cafe/999/save", {"saved": "1"}, fetch=True).status_code == 404


# ---- report a cafe ----

def test_report_cafe(amy, ben):
    amy.post("/add", NEW_CAFE)
    cafe_id = one("SELECT id FROM cafes WHERE name = 'Brand New Place'")
    assert "report this café" in ben.page(f"/cafe/{cafe_id}")
    assert "report this café" not in amy.page(f"/cafe/{cafe_id}")    # can't report your own

    ben.post(f"/cafe/{cafe_id}/report", {"reason": "closed down", "note": "shut last month"})
    ben.post(f"/cafe/{cafe_id}/report", {"reason": "closed down"})   # twice = one open report
    assert one("SELECT COUNT(*) FROM cafe_reports WHERE resolved = 0") == 1
