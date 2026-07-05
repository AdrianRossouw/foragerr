"""The ordered specification set (FRG-SRCH-001, FRG-SRCH-004, decision 7).

Order is cheapest-/most-fundamental-first (an implementation hint, not a
requirement): parsing and mapping gate everything, then the profile, age, term,
and dynamic-store checks. The engine runs *all* of them regardless — order only
affects the sequence reasons appear in.
"""

from __future__ import annotations

from .age import MinAgeSpec, RetentionSpec, YearSanitySpec
from .base import Evaluation, Specification
from .format_ import FormatAllowedSpec, UpgradeAllowedSpec
from .mapping import IssueMatchSpec, SeriesMatchSpec
from .parse import ParseSpec
from .search_match import SearchMatchSpec
from .stores import AlreadyQueuedSpec, BlocklistSpec, FreeSpaceSpec
from .terms import MustContainSpec, MustNotContainSpec


def default_specs() -> tuple[Specification, ...]:
    """The M1 specification set, in evaluation order."""
    return (
        ParseSpec(),
        SeriesMatchSpec(),
        IssueMatchSpec(),
        SearchMatchSpec(),
        YearSanitySpec(),
        FormatAllowedSpec(),
        UpgradeAllowedSpec(),
        RetentionSpec(),
        MinAgeSpec(),
        MustContainSpec(),
        MustNotContainSpec(),
        AlreadyQueuedSpec(),
        BlocklistSpec(),
        FreeSpaceSpec(),
    )


__all__ = [
    "Evaluation",
    "Specification",
    "default_specs",
    "ParseSpec",
    "SeriesMatchSpec",
    "IssueMatchSpec",
    "SearchMatchSpec",
    "YearSanitySpec",
    "FormatAllowedSpec",
    "UpgradeAllowedSpec",
    "RetentionSpec",
    "MinAgeSpec",
    "MustContainSpec",
    "MustNotContainSpec",
    "AlreadyQueuedSpec",
    "BlocklistSpec",
    "FreeSpaceSpec",
]
