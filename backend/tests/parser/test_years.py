"""FRG-IMP-013 — year and cover-date extraction."""

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-013")
def test_standard_and_left_positioned_year_forms():
    r = parse("Batman 404 (1987).cbz", reference_year=2026)
    assert r.year == 1987
    r = parse("Amazing Mary Jane (2019) 002.cbr", reference_year=2026)
    assert r.year == 2019
    assert r.issue.value == 2  # the year is never consumed as the issue


@pytest.mark.req("FRG-IMP-013")
def test_future_years_stay_in_the_title():
    r = parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026)
    assert r.series_name == "Spider-Man 2099"
    assert r.issue.value == 1
    assert r.year == 1992
    # the cutoff is the parameter, not a hardcode
    r = parse("Spider-Man 2099 001 (1992).cbz", reference_year=2100)
    assert r.year == 1992


@pytest.mark.req("FRG-IMP-013")
def test_month_name_iso_and_pre_1900_forms():
    assert parse("Saga 55 (June 2019).cbz", reference_year=2026).year == 2019
    r = parse("Amazing Spider-Man 798 2018-05-22.cbz", reference_year=2026)
    assert r.year == 2018
    # 18xx reprints: no '19'/'20' substring window excludes valid dates
    assert parse("Little Nemo 03 (1889).cbz", reference_year=2026).year == 1889
    # no hardcoded upper bound: a 2098 book is fine with a 2099 reference
    assert parse("Future 01 (2098).cbz", reference_year=2099).year == 2098


@pytest.mark.req("FRG-IMP-013")
def test_six_digit_tokens_are_issues_not_yyyymm_dates():
    r = parse("Cerebus 202004 (1995).cbz", reference_year=2026)
    assert r.issue.value == 202004
    assert r.year == 1995


@pytest.mark.req("FRG-IMP-013")
def test_rightmost_plausible_date_wins():
    r = parse("Batman 1989 404 (1987).cbz", reference_year=2026)
    assert r.year == 1987
    assert r.issue.value == 404


@pytest.mark.req("FRG-IMP-013")
def test_calendar_invalid_iso_dates_are_not_dates():
    # Feb 30 never existed: the ISO branch must not validate it as a date.
    r = parse("Batman 404 (2019-02-30).cbz", reference_year=2026)
    assert r.year is None
    assert r.issue.value == 404
    # A real leap day still validates (datetime handles leap years).
    assert parse("Batman 404 (2020-02-29).cbz", reference_year=2026).year == 2020
    # A calendar-valid ISO date is unaffected.
    assert parse("Batman 404 (2019-05-22).cbz", reference_year=2026).year == 2019
