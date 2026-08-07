"""Strict, secret-safe configuration contract for the main daily report."""

from dataclasses import dataclass, field
import os
import re
from typing import Mapping, Optional


CANONICAL_APP_NAMES = (
    "Unfollowers: Follow & Unfollow",
    "Granny Photos",
    "Otty: Couples&Relationships",
)


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    message: str
    app_name: Optional[str] = None
    metric: Optional[str] = None


@dataclass(frozen=True)
class DailyAppSlot:
    index: int
    name: str
    api_key: Optional[str] = field(default=None, repr=False)
    is_visible: bool = True


@dataclass(frozen=True)
class DailyPortfolio:
    slots: tuple[DailyAppSlot, ...]
    issues: tuple[IntegrityIssue, ...]


def load_daily_portfolio(
    environ: Optional[Mapping[str, str]] = None,
) -> DailyPortfolio:
    """Load only the three immutable production slots used by the main report."""
    source = os.environ if environ is None else environ
    slots: list[DailyAppSlot] = []
    issues: list[IntegrityIssue] = []

    for index, expected_name in enumerate(CANONICAL_APP_NAMES, start=1):
        key = source.get(f"ADAPTY_API_KEY_APP{index}", "").strip()
        actual_name = source.get(f"ADAPTY_APP_NAME_{index}", "").strip()
        fetchable_key: Optional[str] = key or None

        if actual_name != expected_name:
            fetchable_key = None
            issues.append(IntegrityIssue(
                code="config.wrong_name",
                message=(
                    f"APP{index}: expected '{expected_name}', "
                    f"got '{actual_name or 'empty'}'"
                ),
                app_name=expected_name,
            ))
        if not key:
            issues.append(IntegrityIssue(
                code="config.missing_key",
                message=f"APP{index}: Secret API key is missing",
                app_name=expected_name,
            ))

        slots.append(DailyAppSlot(
            index=index - 1,
            name=expected_name,
            api_key=fetchable_key,
        ))

    if any(
        re.fullmatch(
            r"ADAPTY_(?:API_KEY_APP|APP_NAME_)(?:[4-9]|[1-9][0-9]+)",
            name,
        )
        for name in source
    ):
        issues.append(IntegrityIssue(
            code="config.extra_slot",
            message="APP4+ variables are ignored by the daily report",
        ))

    if any(
        re.fullmatch(r"ADAPTY_APP_VISIBLE_[1-9][0-9]*", name)
        for name in source
    ):
        issues.append(IntegrityIssue(
            code="config.visibility_override",
            message="visibility overrides are ignored by the daily report",
        ))

    return DailyPortfolio(slots=tuple(slots), issues=tuple(issues))
