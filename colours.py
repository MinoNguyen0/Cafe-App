# colours.py
# helpers for the "colours" filter on the home page.
#
# the idea: you pick your oshi's member colour (e.g. green) and the site
# shows cafes whose palette has something close to that colour.

# basic member colours. tweak the hex codes if a shade looks off to you
OSHI_COLOURS = {
    "red": "#e53935",
    "pink": "#f48fb1",
    "orange": "#fb8c00",
    "yellow": "#fdd835",
    "green": "#7cb342",
    "blue": "#64b5f6",
    "purple": "#9575cd",
    "brown": "#8d6e63",
    "black": "#212121",
    "white": "#ffffff",
}


def hex_to_rgb(hex_code):
    # "#8dbf3a" -> (141, 191, 58)
    h = hex_code.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def colour_distance(a, b):
    # how "far apart" two colours are. 0 = identical, ~441 = black vs white.
    # it's just pythagoras in 3D (r, g, b). not perfect for how eyes see
    # colour but good enough for this.
    r1, g1, b1 = hex_to_rgb(a)
    r2, g2, b2 = hex_to_rgb(b)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def palette_matches(palette, target_hex, max_distance=90):
    # palette is the list of hex strings for one cafe.
    # NOTE: if the filter feels too strict/loose, change max_distance
    return any(colour_distance(c, target_hex) <= max_distance for c in palette)
