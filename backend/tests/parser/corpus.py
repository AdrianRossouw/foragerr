"""The parser regression corpus (FRG-IMP-021).

All 75 rows from `docs/research/mylar-filename-parsing.md` §3 (67 primary +
8 supplementary), asserted with the *corrected/desired* expectations — not
Mylar's behavior. Research-flagged rows are pinned to the desired column:

* row 25 — issue 30, `Cover B` is a cover-variant annotation (never `30 B`)
* row 42 — `Part 2` is an issue/chapter cue: both volume fields None
* row 43 — roman-numeral volume captured: ordinal 3 (not silently lost)
* row 50 — two-word `Graphic Novel` matches: booktype GN
* row 58 — `Summer Special` consumed with the marker: series `Archie`

POLICY (additive-only): rows are never deleted or weakened. Every parser
bug fix adds its reproducing row here *before* the fix lands. Expectation
corrections are deliberate pinned-behavior changes citing the governing
requirement ID in the commit message.

Notes on deliberate M1 pins:
* row 63 (story-arc reading-order prefix) — arc-prefix handling is
  FRG-IMP-025 (milestone B, explicitly out of M1 scope), so M1 pins the
  no-arc-mode behavior: the `023-Batman` token stays in the title. The row
  will be re-pinned when FRG-IMP-025 lands.
* row 52 — volume fields None (Mylar fabricated v1; FRG-IMP-016 fabricates
  v1 only for explicit trade formats).
* rows 11/74 — the generic trailing-annotation rules (FRG-IMP-017) also
  classify `Empire` as scan group and `Complete` as an edition tag.

Every row carries the FRG-IMP requirement IDs it evidences; the executor in
``test_corpus.py`` emits them as pytest ``req`` marks for the traceability
matrix (FRG-PROC-004/005).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_EXTS = {"cbz", "cbr", "cb7", "cbt", "pdf"}


@dataclass(frozen=True)
class Row:
    n: int
    filename: str
    series: str | None
    reqs: tuple[str, ...]
    # issue record expectations (value as exact Fraction-compatible string)
    issue: str | None = None
    display: str | None = None
    suffix: str | None = None
    issue_name: str | None = None
    classification: str = "regular"
    # structured range / count
    range_start: str | None = None
    range_end: str | None = None
    range_display: str | None = None
    total: str | None = None
    # volume / year / type
    vol: int | None = None
    vol_year: int | None = None
    year: int | None = None
    booktype: str = "issue"
    scan_group: str | None = None
    # `(fN)` fixed-release marker revision (duplicate-constraint parser extension)
    fix_revision: int | None = None
    issue_id: str | None = None
    alt_series: str | None = None
    alt_issue_title: str | None = None
    # (kind-value, text) pairs that must appear in result.annotations
    annotations_contain: tuple[tuple[str, str], ...] = field(default=())

    @property
    def ext(self) -> str | None:
        tail = self.filename.rsplit(".", 1)
        if len(tail) == 2 and tail[1].lower() in _EXTS:
            return tail[1].lower()
        return None


CORPUS: tuple[Row, ...] = (
    Row(1, "Batman 404 (1987).cbz", "Batman", ("FRG-IMP-007", "FRG-IMP-013", "FRG-IMP-016"),
        issue="404", display="404", year=1987),
    Row(2, "Batman #404 (1987).cbr", "Batman", ("FRG-IMP-007", "FRG-IMP-003"),
        issue="404", display="404", year=1987),
    Row(3, "Batman 404.cbz", "Batman", ("FRG-IMP-003", "FRG-IMP-007"),
        issue="404", display="404"),
    Row(4, "100 Bullets 050 (2003).cbz", "100 Bullets", ("FRG-IMP-007",),
        issue="50", display="050", year=2003),
    Row(5, "52 018 (2006).cbz", "52", ("FRG-IMP-007",),
        issue="18", display="018", year=2006),
    Row(6, "2000AD prog 2205 (2020).cbz", "2000AD prog", ("FRG-IMP-007", "FRG-IMP-013"),
        issue="2205", display="2205", year=2020),
    Row(7, "Spider-Man 2099 001 (1992).cbz", "Spider-Man 2099", ("FRG-IMP-002", "FRG-IMP-013"),
        issue="1", display="001", year=1992),
    Row(8, "Batman Beyond 2.0 015 (2013).cbz", "Batman Beyond 2.0", ("FRG-IMP-004",),
        issue="15", display="015", year=2013),
    Row(9, "X-23 012 (2011).cbz", "X-23", ("FRG-IMP-019",),
        issue="12", display="012", year=2011),
    Row(10, "Amazing Mary Jane (2019) 002.cbr", "Amazing Mary Jane", ("FRG-IMP-007", "FRG-IMP-013"),
        issue="2", display="002", year=2019),
    Row(11, "Amazing.Spider-Man.798.2018.Digital.Empire.cbr", "Amazing Spider-Man",
        ("FRG-IMP-004", "FRG-IMP-017", "FRG-IMP-019"),
        issue="798", display="798", year=2018, scan_group="Empire",
        annotations_contain=(("edition", "Digital"),)),
    Row(12, "Invincible 015.5 (2005).cbz", "Invincible", ("FRG-IMP-008",),
        issue="15.5", display="015.5", year=2005),
    Row(13, "Elephantmen 20.5 (2009).cbz", "Elephantmen", ("FRG-IMP-008",),
        issue="20.5", display="20.5", year=2009),
    Row(14, "Gold Digger 0.5 (1997).cbr", "Gold Digger", ("FRG-IMP-008",),
        issue="0.5", display="0.5", year=1997),
    Row(15, "Deadpool -1 (1997).cbz", "Deadpool", ("FRG-IMP-008",),
        issue="-1", display="-1", year=1997),
    Row(16, "Uncanny X-Men ½ (1999).cbz", "Uncanny X-Men", ("FRG-IMP-008", "FRG-IMP-005"),
        issue="1/2", display="½", year=1999),
    Row(17, "Batman 000.0000½ (2015).cbz", "Batman", ("FRG-IMP-008",),
        issue="1/2", display="000.0000½", year=2015),
    Row(18, "Wolverine 027AU (2013).cbz", "Wolverine", ("FRG-IMP-009",),
        issue="27", display="027AU", suffix="AU", year=2013),
    Row(19, "Age of Ultron 10 AI (2013).cbz", "Age of Ultron", ("FRG-IMP-009",),
        issue="10", display="10 AI", suffix="AI", year=2013),
    Row(20, "Uncanny Avengers 008.NOW (2013).cbz", "Uncanny Avengers", ("FRG-IMP-009",),
        issue="8", display="008.NOW", suffix="NOW", year=2013),
    Row(21, "Mighty Avengers 004.INH (2013).cbz", "Mighty Avengers", ("FRG-IMP-009",),
        issue="4", display="004.INH", suffix="INH", year=2013),
    Row(22, "Spider-Verse 001.MU (2015).cbz", "Spider-Verse", ("FRG-IMP-009",),
        issue="1", display="001.MU", suffix="MU", year=2015),
    Row(23, "Avengers 024.NOW! (2014).cbz", "Avengers", ("FRG-IMP-009",),
        issue="24", display="024.NOW", suffix="NOW", year=2014),
    Row(24, "Amazing Spider-Man 015A (2014).cbz", "Amazing Spider-Man", ("FRG-IMP-009",),
        issue="15", display="015A", suffix="A", year=2014),
    # row 25 pinned to the desired column: Cover B is an annotation
    Row(25, "Justice League 30 Cover B (2019).cbz", "Justice League",
        ("FRG-IMP-009", "FRG-IMP-011", "FRG-IMP-021"),
        issue="30", display="30", year=2019,
        annotations_contain=(("cover-variant", "Cover B"),)),
    Row(26, "Fantastic Four 600-X (2012).cbz", "Fantastic Four", ("FRG-IMP-009",),
        issue="600", display="600-X", suffix="X", year=2012),
    Row(27, "Wolverine 050-X (2010).cbr", "Wolverine", ("FRG-IMP-009",),
        issue="50", display="050-X", suffix="X", year=2010),
    Row(28, "Secret Wars #Alpha (2015).cbz", "Secret Wars", ("FRG-IMP-009",),
        issue_name="Alpha", display="Alpha", year=2015),
    Row(29, "Batman Black and White 03 (2013).cbz", "Batman Black and White", ("FRG-IMP-009",),
        issue="3", display="03", year=2013),
    Row(30, "Gideon Falls Director's Cut 1 (2018).cbz", "Gideon Falls",
        ("FRG-IMP-009", "FRG-IMP-017"),
        issue="1", display="1", year=2018,
        annotations_contain=(("edition", "Director's Cut"),)),
    Row(31, "Batman 39 (of 52) (2017).cbz", "Batman", ("FRG-IMP-011",),
        issue="39", display="39", total="52", year=2017),
    Row(32, "Kick-Ass 3 01 (of 08) (2013).cbz", "Kick-Ass 3", ("FRG-IMP-011", "FRG-IMP-007"),
        issue="1", display="01", total="8", year=2013),
    Row(33, "Empowered 01 (of 7.3) (2015).cbz", "Empowered", ("FRG-IMP-011",),
        issue="1", display="01", total="7.3", year=2015),
    Row(34, "Descender 011 (2 covers) (2016).cbz", "Descender", ("FRG-IMP-011",),
        issue="11", display="011", year=2016,
        annotations_contain=(("covers", "2 covers"),)),
    Row(35, "Saga 55 (2018) (digital) (36p ctc).cbz", "Saga",
        ("FRG-IMP-004", "FRG-IMP-011", "FRG-IMP-017"),
        issue="55", display="55", year=2018,
        annotations_contain=(("edition", "digital"), ("page-tag", "36p ctc"))),
    Row(36, "Lazarus 01 (2013) (1440px).cbz", "Lazarus", ("FRG-IMP-011", "FRG-IMP-017"),
        issue="1", display="01", year=2013,
        annotations_contain=(("page-tag", "1440px"),)),
    Row(37, "Batman v2 015 (2012).cbz", "Batman", ("FRG-IMP-012",),
        issue="15", display="015", vol=2, year=2012),
    Row(38, "Batman Vol. 2 015 (2012).cbz", "Batman", ("FRG-IMP-012",),
        issue="15", display="015", vol=2, year=2012),
    Row(39, "Batman Volume 2 015 (2012).cbz", "Batman", ("FRG-IMP-012",),
        issue="15", display="015", vol=2, year=2012),
    Row(40, "Justice League v2017 021 (2018).cbz", "Justice League",
        ("FRG-IMP-012", "FRG-IMP-013"),
        issue="21", display="021", vol_year=2017, year=2018),
    Row(41, "Iron Man v5 023 (2013).cbz", "Iron Man", ("FRG-IMP-012",),
        issue="23", display="023", vol=5, year=2013),
    # row 42 pinned to the desired column: Part N is not a volume
    Row(42, "Astonishing X-Men Part 2 (2018).cbz", "Astonishing X-Men",
        ("FRG-IMP-012", "FRG-IMP-021"),
        issue="2", display="2", year=2018),
    # row 43 pinned to the desired column: roman-numeral volume captured
    Row(43, "Sandman Vol III 05 (1991).cbz", "Sandman", ("FRG-IMP-012", "FRG-IMP-021"),
        issue="5", display="05", vol=3, year=1991),
    Row(44, "Casper (1953-) 001.cbz", "Casper", ("FRG-IMP-012", "FRG-IMP-013"),
        issue="1", display="001", vol_year=1953),
    Row(45, "Saga TPB v01 (2013).cbz", "Saga", ("FRG-IMP-016",),
        vol=1, year=2013, booktype="TPB"),
    Row(46, "Monstress Vol. 06 (2021) (Digital) TPB.cbz", "Monstress", ("FRG-IMP-016",),
        vol=6, year=2021, booktype="TPB",
        annotations_contain=(("edition", "Digital"),)),
    Row(47, "East of West TPB (2014).cbz", "East of West", ("FRG-IMP-016",),
        vol=1, year=2014, booktype="TPB"),
    Row(48, "Watchmen HC (1988).cbz", "Watchmen", ("FRG-IMP-016",),
        vol=1, year=1988, booktype="HC"),
    Row(49, "Blacksad GN (2010).cbz", "Blacksad", ("FRG-IMP-016",),
        vol=1, year=2010, booktype="GN"),
    # row 50 pinned to the desired column: two-word Graphic Novel matches
    Row(50, "Pride of Baghdad Graphic Novel (2006).cbz", "Pride of Baghdad",
        ("FRG-IMP-016", "FRG-IMP-021"),
        vol=1, year=2006, booktype="GN"),
    Row(51, "Kill or be Killed v1 (2017) (Digital TPB).cbz", "Kill or be Killed",
        ("FRG-IMP-016",),
        vol=1, year=2017, booktype="TPB"),
    Row(52, "Superman Smashes the Klan 2020 (2020).cbz", "Superman Smashes the Klan 2020",
        ("FRG-IMP-014", "FRG-IMP-016"),
        year=2020, booktype="one-shot"),
    Row(53, "Batman Annual 02 (2017).cbz", "Batman", ("FRG-IMP-015",),
        issue="2", display="02", classification="annual", year=2017),
    Row(54, "Wolverine 1997 Annual.cbz", "Wolverine", ("FRG-IMP-015",),
        issue="1997", display="1997", classification="annual", year=1997),
    Row(55, "Batman Annual 2021 (2021).cbz", "Batman", ("FRG-IMP-014", "FRG-IMP-015"),
        issue="2021", display="2021", classification="annual", year=2021),
    Row(56, "Deadpool BiAnnual 01 (2014).cbz", "Deadpool", ("FRG-IMP-015",),
        issue="1", display="01", classification="biannual", year=2014),
    Row(57, "Gotham City Sirens Special 1 (2022).cbz", "Gotham City Sirens", ("FRG-IMP-015",),
        issue="1", display="1", classification="special", year=2022),
    # row 58 pinned to the desired column: Summer consumed with the marker
    Row(58, "Archie Summer Special 3 (1996).cbz", "Archie", ("FRG-IMP-015", "FRG-IMP-021"),
        issue="3", display="3", classification="special", year=1996),
    Row(59, "Justice League Dark 016 (2019) (Webrip) (The Last Kryptonian-DCP).cbz",
        "Justice League Dark", ("FRG-IMP-017",),
        issue="16", display="016", year=2019, scan_group="The Last Kryptonian-DCP",
        annotations_contain=(("edition", "Webrip"),)),
    Row(60, "Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz",
        "Invincible Iron Man", ("FRG-IMP-017", "FRG-IMP-001"),
        issue="19", display="019", year=2016, scan_group="Minutemen-Faessla",
        annotations_contain=(("edition", "Digital"),)),
    Row(61, "Southern Bastards 09 (2015) (digital) (Son of Ultron-Empire).cbr",
        "Southern Bastards", ("FRG-IMP-017",),
        issue="9", display="09", year=2015, scan_group="Son of Ultron-Empire"),
    Row(62, "Batman.Annual.02.2017.digital.Glorith-HD.cbz", "Batman",
        ("FRG-IMP-015", "FRG-IMP-017", "FRG-IMP-004"),
        issue="2", display="02", classification="annual", year=2017,
        scan_group="Glorith-HD",
        annotations_contain=(("edition", "digital"),)),
    # row 63: arc reading-order prefixes are FRG-IMP-025 (milestone B, out of
    # M1 scope) — pin the no-arc-mode behavior for now (see module docstring).
    Row(63, "023-Batman 404 (1987).cbz", "023-Batman", ("FRG-IMP-007",),
        issue="404", display="404", year=1987),
    Row(64, "Batman - The Long Halloween 05 (1997).cbz", "Batman - The Long Halloween",
        ("FRG-IMP-019",),
        issue="5", display="05", year=1997,
        alt_series="Batman", alt_issue_title="The Long Halloween"),
    Row(65, "Daredevil 600 - Mayor Fisk (2018).cbz", "Daredevil",
        ("FRG-IMP-007", "FRG-IMP-019"),
        issue="600", display="600", year=2018, alt_issue_title="Mayor Fisk"),
    Row(66, "Batman 404 [__123456__] (1987).cbz", "Batman", ("FRG-IMP-018",),
        issue="404", display="404", year=1987, issue_id="123456"),
    Row(67, "Scott Pilgrim & The Infinite Sadness v3 (2006).cbz",
        "Scott Pilgrim & The Infinite Sadness",
        ("FRG-IMP-005", "FRG-IMP-008", "FRG-IMP-012"),
        vol=3, year=2006),
    Row(68, "Batman 404 (1987).CBZ", "Batman", ("FRG-IMP-006",),
        issue="404", display="404", year=1987),
    Row(69, "Batman_404_(1987).cbz", "Batman", ("FRG-IMP-004",),
        issue="404", display="404", year=1987),
    Row(70, "Batman,404,(1987).cbz", "Batman", ("FRG-IMP-004",),
        issue="404", display="404", year=1987),
    Row(71, "Teen Titans v1 Annual 1 (1967).cbz", "Teen Titans",
        ("FRG-IMP-012", "FRG-IMP-015"),
        issue="1", display="1", classification="annual", vol=1, year=1967),
    Row(72, "Star Wars Legacy II 03 (2013).cbz", "Star Wars Legacy II",
        ("FRG-IMP-012", "FRG-IMP-019"),
        issue="3", display="03", year=2013),
    Row(73, "Berserk v01 c01-05.cbz", "Berserk", ("FRG-IMP-010", "FRG-IMP-012"),
        range_start="1", range_end="5", range_display="c01-05", vol=1),
    Row(74, "Preacher 01-66 Complete.cbz", "Preacher", ("FRG-IMP-010", "FRG-IMP-003"),
        range_start="1", range_end="66", range_display="01-66",
        annotations_contain=(("edition", "Complete"),)),
    Row(75, "4001 A.D. 001 (2016).cbz", "4001 A.D.", ("FRG-IMP-007",),
        issue="1", display="001", year=2016),
    # --- rows 76+ added under the additive growth policy (FRG-IMP-021) ---
    # 76/77: real-library shapes found during the mounted-library sweep —
    # fully hyphen-mangled and plus-mangled (URL-encoded) release names.
    Row(76, "Justice-League-Beyond-005--2012---digital-Empire-.cbr",
        "Justice League Beyond", ("FRG-IMP-004", "FRG-IMP-021"),
        issue="5", display="005", year=2012, scan_group="Empire",
        annotations_contain=(("edition", "digital"),)),
    Row(77, "Swamp+Thing+003+(2012)+(digital)+(Empire-ZurEnArrh).cbz",
        "Swamp Thing", ("FRG-IMP-004", "FRG-IMP-017", "FRG-IMP-021"),
        issue="3", display="003", year=2012, scan_group="Empire-ZurEnArrh",
        annotations_contain=(("edition", "digital"),)),
    # 78: a disqualified issue candidate (suffix A) is NOT volume evidence —
    # a trade format only fabricates v1 with no numeric candidate at all
    # (FRG-IMP-016). The suffixed issue survives; volume stays None.
    Row(78, "Saga TPB 05A (2013).cbz", "Saga", ("FRG-IMP-016", "FRG-IMP-021"),
        issue="5", display="05A", suffix="A", year=2013, booktype="TPB"),
    # 79-81: `(fN)` fixed-release markers (duplicate-constraint parser extension; corpus
    # rows carry the FRG-IMP annotation-classification ids per the row policy —
    # the requirement-tagged marker tests live in test_fix_markers.py).
    # 79: a trailing marker is captured (and is NOT mistaken for a scan group).
    Row(79, "Batman 404 (1987) (f2).cbz", "Batman", ("FRG-IMP-017", "FRG-IMP-021"),
        issue="404", display="404", year=1987, fix_revision=2,
        annotations_contain=(("fix-marker", "f2"),)),
    # 80: scene shape — the marker sits among trailing groups and the real scan
    # group still wins the trailing-annotation selection.
    Row(80, "Saga 055 (2019) (Digital) (f1) (Son of Ultron-Empire).cbz", "Saga",
        ("FRG-IMP-017", "FRG-IMP-021"),
        issue="55", display="055", year=2019, scan_group="Son of Ultron-Empire",
        fix_revision=1,
        annotations_contain=(("edition", "Digital"), ("fix-marker", "f1"))),
    # 81: title-plausibility guard — an `(f1)` group BEFORE the issue is title
    # context, never a fix marker (fix_revision stays None, kind stays generic).
    Row(81, "Batman (f1) 404 (1987).cbz", "Batman", ("FRG-IMP-017", "FRG-IMP-021"),
        issue="404", display="404", year=1987,
        annotations_contain=(("generic", "f1"),)),
)

assert len(CORPUS) == 81
assert [r.n for r in CORPUS] == list(range(1, 82))
