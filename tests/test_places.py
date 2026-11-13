# tests for places.py - the small helper functions (no website needed)

import pytest

from places import clean_handle, clean_website, metres_apart, names_match, simplify_name


@pytest.mark.parametrize("typed, expected", [
    ("@nanas.melb", "nanas.melb"),
    ("nanas.melb", "nanas.melb"),
    ("https://www.instagram.com/nanas.melb/", "nanas.melb"),
    ("instagram.com/nanas.melb", "nanas.melb"),
    ("https://www.tiktok.com/@nanas.melb?lang=en", "nanas.melb"),
    ("<script>", ""),
    ("", ""),
])
def test_clean_handle(typed, expected):
    assert clean_handle(typed) == expected


@pytest.mark.parametrize("typed, expected", [
    ("nanasgreentea.com.au", "https://nanasgreentea.com.au"),
    ("http://a.com/menu", "http://a.com/menu"),
    ("https://a.com", "https://a.com"),
    ("javascript:alert(1)", ""),   # would run code if someone clicked it
    ("not a website", ""),
    ("", ""),
])
def test_clean_website(typed, expected):
    assert clean_website(typed) == expected


def test_simplify_name_drops_filler_words_and_accents():
    assert simplify_name("The Butter Room Café!") == "butterroom"


@pytest.mark.parametrize("a, b", [
    ("nanas", "Nana's Green Tea"),
    ("The Butter Room Café", "Butter Room"),
    ("Wooss", "Woos"),            # typo
    ("AMIRI CAFE", "Amiri"),
])
def test_names_that_match(a, b):
    assert names_match(a, b)


@pytest.mark.parametrize("a, b", [
    ("Wooss", "Nana's Green Tea"),
    ("Cafe", "Coffee Bar"),        # only filler words
    ("", "Wooss"),
])
def test_names_that_dont_match(a, b):
    assert not names_match(a, b)


def test_metres_apart():
    # AMIRI (QV) to Wooss (La Trobe St) is about 210m
    assert 200 < metres_apart(-37.81104, 144.96585, -37.8099, 144.9639) < 225
    assert metres_apart(-37.8, 144.9, -37.8, 144.9) == 0
