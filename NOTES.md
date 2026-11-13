# Oshi Collective - notes

## How to run it

Open a terminal in this folder (`E:\Cafe`) and run:

    .venv\Scripts\python app.py

Then go to http://127.0.0.1:5000 in your browser. Stop it with Ctrl+C.

First time on a new computer (no `.venv` folder yet):

    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt

(`.venv` is a private copy of python just for this project, so installing
flask doesn't mess with anything else on your computer.)

## Tests

The `tests/` folder checks the whole site automatically (103 checks, about 12 seconds):

    .venv\Scripts\python -m pytest

- all green = everything still works. Run it after you change something!
- `-v` shows every test name, `tests/test_admin.py` runs just one file
- the tests use a **throwaway database and uploads folder** and fake map lookups, so they never touch
  your real `cafe.db` or photos, and don't need internet (see `tests/conftest.py`)
- each file covers one area: `test_accounts`, `test_cafes`, `test_posts`, `test_admin`, `test_pages`,
  `test_places`
- adding a feature? copy a test that's close to it and change it. `amy`, `ben`, `admin` and `browser`
  are ready-made pretend users (see `conftest.py`)

## Git / GitHub

The code is on https://github.com/MinoNguyen0/Cafe-App. To save + upload your changes:

    git add -A
    git commit -m "what you changed"
    git push

`cafe.db`, `secret_key.txt`, `.venv` and uploaded photos are in `.gitignore`, so they never get uploaded.

## The pages

| url | page | needs login? |
|---|---|---|
| `/` | landing page (big stars, GET STARTED) | no (skips to /home if logged in) |
| `/home` | featured cafe carousel, What's New, posts from people you follow | no |
| `/feed` | posts, with For You / Following / Your Oshis / Explore tabs | Following + Your Oshis do |
| `/cafes` | search + filter cafes, the cards with colour palettes | no |
| `/map` | every cafe as a pin on a map (same filters as /cafes) | no |
| `/cafe/3` | one cafe: palette, links, small map, gallery, comments | to comment |
| `/cafe/3/edit` | edit a cafe: links, map pin, photo, palette | yes |
| `/saved` | the star: cafés you hearted + posts you liked | yes |
| `/post` | the yellow + button: new post (photo required) | yes |
| `/add` | add a cafe | yes |
| `/u/mina` | someone's profile, follow button, their posts | to follow |
| `/signup` `/login` | accounts | - |
| `/account/password` | change password (from your profile) | yes |
| `/account/delete` | delete your account (from your profile) | yes |
| `/admin` | reported cafés + reported comments | admins only |

Bottom nav, left to right: home, feed, **cafés** in the middle (opens the list or the map, whichever you used last), **saved**, add a cafe.
"‹ back" on a cafe page goes back to wherever you came from (map, list, feed, saved...).
Both of those use little notes the browser keeps (`localStorage` / `sessionStorage`). The script is at the bottom of `base.html`.

## What each file does

| file | what it's for |
|---|---|
| `app.py` | all the pages. start reading here |
| `admin.py` | the admin page + admin-only actions (delete / merge cafés) |
| `cleanup.py` | deleting things properly (rows that point at them + photo files) |
| `auth.py` | sign up / log in / log out + `@login_required` |
| `db.py` | the database tables (there's a diagram in the comments) |
| `places.py` | address lookup (for map pins) + cleaning up website/instagram/tiktok links |
| `colours.py` | the "colours" filter maths (finds cafes close to your oshi colour) |
| `templates/base.html` | top bar + bottom nav, shared by every page |
| `templates/_bits.html` | reusable pieces: stars, palette dots, cafe card, post card |
| `templates/_filters.html` | the List/Map switch + filter row, shared by /cafes and /map |
| `templates/_map_head.html` | loads the map library + makes the palette-coloured pins |
| `templates/cafe_form.html` | the add AND edit cafe form (one file for both) |
| `templates/*.html` | one file per page (names match the table above) |
| `static/style.css` | all the styling. colours are at the top |
| `static/uploads/` | photos people upload |
| `cafe.db` | **the database** (made automatically on first run) |
| `secret_key.txt` | made automatically. signs login cookies. **never share or upload it** |

## The database

It's SQLite: the whole database is the one file `cafe.db`. Python has SQLite
built in, so there's no database server to install. Tables:

- **users**: username + *hashed* password, oshis, bio, avatar (profile picture file), is_admin
- **cafes**: name, address, palette, cover photo, lat/lng (map pin), website, instagram, tiktok
- **comments**: reviews. A comment **with a photo** also shows up as a post in the feed.
- **follows**: who follows who
- **saved_cafes**: the hearts on cafe cards (your Saved page)
- **likes**: hearts on posts
- **reports** / **hidden_comments**: the report and hide buttons on comments
- **cafe_reports**: "report this café" (resolved = 1 once an admin dealt with it)

To look inside it, get **DB Browser for SQLite** (free) and open `cafe.db`.
To start completely fresh, stop the app, delete `cafe.db` and the photos in
`static/uploads/`, then start it again.

## Accounts and passwords

- Passwords are never saved as-is. They're stored as a **hash** (scrambled
  one way), so even someone with `cafe.db` can't read them. See the top of `auth.py`.
- When you log in, your user id goes into a signed cookie (`session`). Before every page,
  `load_logged_in_user()` in `auth.py` looks you up and puts you in `g.user`.
- `@login_required` on a route sends logged-out people to the login page, then
  back to where they were (`?next=`).
- **CSRF tokens:** every form has a hidden `{{ csrf_input() }}`. It stops other
  websites from submitting forms on your behalf. If you add a new
  `<form method="post">`, **you must put `{{ csrf_input() }}` inside it** or
  submitting it gives "400 Bad Request".

## Admin

**Choi_Mino is an admin.** There's no button on the site to make someone admin (that would be a security hole).
You do it from a terminal in `E:\Cafe`:

    .venv\Scripts\python db.py make-admin USERNAME
    .venv\Scripts\python db.py remove-admin USERNAME

Admins can:
- open **/admin** (link on your profile). It lists reported cafés (with reasons + notes) and reported comments.
- **edit any café**, not just their own. This also fixes cafés whose owner deleted their account.
- **remove any comment** ("remove (admin)" under comments).
- on a café page, use the dashed **admin** box to:
  - **merge** a duplicate into the real café: comments, photos, likes and saves move over, then the duplicate is deleted.
    Cafés that look similar are listed first in the dropdown.
  - **delete** the café with everything on it.

**Are you sure?** Merge, delete café, remove/delete comment and the admin page buttons all open a
popup first that says exactly what will happen. Cancel is the default, so Enter or Escape never
deletes anything by accident. To add the popup to any new form, give it `data-confirm="your question"`
(and `data-confirm-yes="button text"`). The script is in `base.html`.

## Adding a café that already exists

- While you type the name or drop the pin, the form shows **"already on Oshi Collective?"** with
  look-alike cafés (`/cafes/similar`, `find_similar_cafes()` in `app.py`).
- If you save anyway and it still looks like a duplicate, you get a **"Wait - is it one of these?"** page.
  "add it anyway" goes through, because a chain can have 2 branches.
- "Looks like" = nearly the same name (`names_match()` in `places.py` ignores "the", "cafe", accents,
  typos...) or a pin within 30m of another café.

## Deleting an account

On your profile, tap **delete account**. You need your password and the tick box (`delete_account()` in `auth.py`).
It deletes the user, their comments/posts + photos, profile picture, likes, reports, hides, saves and
follows (both ways). **Cafes they added stay** with no owner, so other people's reviews aren't lost
(but then nobody can edit those cafes).

## Delete / hide / report

- **Delete:** only on your own comments. The server checks `comments.user_id`
  matches you (hiding the button alone isn't enough, because anyone can send requests by
  hand). It also deletes the photo, likes and reports.
- **Hide:** hides someone else's comment for you only, and you can "show again".
- **Report:** pick a reason, and it's also hidden for you. At `REPORT_LIMIT`
  reports (3, in `db.py`) it's hidden for everyone except the author.

## How a post gets made (the full trip)

1. you press + on the feed, so `new_post()` in `app.py` shows `new_post.html`
2. you submit, so the browser sends the form + photo (and the csrf token)
3. `check_csrf()` makes sure the token matches
4. `@login_required` makes sure you're logged in
5. `create_comment()` checks the fields, saves the photo with `save_photo()`, and
   INSERTs a row into `comments` with your `user_id`
6. you're redirected to `/feed`, and `get_posts()` reads it back out

## The map + cafe links

- `/cafes` and `/map` share one filter bar (`_filters.html`) with a **list / map** switch at the top.
  Switching keeps your filters. `keep` and `top_toggle` in `filter_cafes()` build those links.

- The map uses **Leaflet** (a free map library) with **OpenStreetMap**. There's no account, API key or cost.
  It's loaded from the internet, so the map needs wifi to show.
- Each pin is a little pie chart of the cafe's palette (`palettePin()` in `_map_head.html`).
- To place a pin, there's a map on the add/edit form. Tap it, drag the pin, or press
  "find the street on the map". If you save without placing one, it tries to find the address
  automatically (`find_address()` in `places.py`, which uses OpenStreetMap's free address search).
- **Wooss** isn't on OpenStreetMap, so its pin is a rough guess on La Trobe St. Fix it with
  "edit café" by dragging the pin to the right spot.
- Links: paste an Instagram/TikTok handle *or* the full link, and `clean_handle()` keeps just the handle.
  Websites must be normal `http(s)://` links. `javascript:` links get rejected, because that's
  a classic way to sneak code onto a site.
- **Only the person who added a cafe can edit it** (checked in `edit_cafe()` in `app.py`;
  everyone else gets "403 Forbidden"). The 4 starter cafes belong to the Choi_Mino account.
  If you start fresh with a new `cafe.db`, they'll have no owner, so nobody can edit them until you run:
  `.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('cafe.db'); c.execute(\"UPDATE cafes SET added_by=(SELECT id FROM users WHERE username='Choi_Mino') WHERE added_by IS NULL\"); c.commit()"`
- "directions" on a cafe page opens Google Maps with the cafe as the destination.
- "near me" asks your browser for your location. It only moves the map and is never sent to the server.

## Profile pictures

Upload one from **edit profile** on your own profile page. It previews before you save,
and "remove my picture" goes back to the letter. The old file is deleted when you
change or remove it. The `avatar()` macro in `_bits.html` draws it everywhere
(top bar, profile, posts, comments) and shows your first letter if there's no picture.

## Handy things to know

- **Change the theme:** edit the `:root` colours at the top of `style.css`.
- **Colour filter too strict/loose?** change `max_distance` in `colours.py`.
- **Star ratings** are the average of everyone's comment ratings.
- **Hearts on cafe cards** save the cafe to your account (Saved page). Hearts on posts are likes.
  Old browser-only hearts get moved onto your account automatically the next time you visit logged in.
- The 5-star badge on a post means that person gave the cafe 5 stars.

## Ideas for next

- edit your own comment
- admin page to look at reports
- pick palette colours automatically from the cover photo
- "What's New" for merch / collab announcements (like the figma) instead of just new cafes
