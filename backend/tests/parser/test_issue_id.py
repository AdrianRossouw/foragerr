"""FRG-IMP-018 — embedded issue-ID pass-through."""

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-018")
def test_mid_name_embedded_id_extracted_and_removed():
    tagged = parse("Batman 404 [__123456__] (1987).cbz", reference_year=2026)
    plain = parse("Batman 404 (1987).cbz", reference_year=2026)
    assert tagged.issue_id == "123456"
    td, pd = tagged.to_dict(), plain.to_dict()
    td.pop("issue_id"), pd.pop("issue_id")
    assert td == pd  # all other fields exactly as without the tag
    assert "123456" not in (tagged.series_name or "")
    assert all("123456" not in a.text for a in tagged.annotations)


@pytest.mark.req("FRG-IMP-018")
def test_tag_recognized_anywhere_in_the_name():
    lead = parse("[__987654__] Saga 55 (2018).cbz", reference_year=2026)
    trail = parse("Saga 55 (2018) [__987654__].cbz", reference_year=2026)
    for r in (lead, trail):
        assert r.issue_id == "987654"
        assert r.series_name == "Saga"
        assert r.issue.value == 55
        assert r.year == 2018


@pytest.mark.req("FRG-IMP-018")
def test_absent_tag_is_none_and_plain_brackets_are_not_ids():
    assert parse("Batman 404 (1987).cbz", reference_year=2026).issue_id is None
    r = parse("Batman 404 [123456] (1987).cbz", reference_year=2026)
    assert r.issue_id is None  # only the exact [__<id>__] convention
    assert ("generic", "123456") in {(a.kind.value, a.text) for a in r.annotations}
