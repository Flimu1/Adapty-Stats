"""Strict client for experiment-scoped A/B metrics used by Adapty Dashboard."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import requests


logger = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://api-admin.adapty.io/api/v1"


class AdaptyDashboardError(RuntimeError):
    """Dashboard authentication, identity, or response-contract failure."""


@dataclass(frozen=True)
class AdaptyAbVariantMetrics:
    label: str
    paywall_id: str
    paywall_name: str
    revenue: float
    arpas: float
    views: int
    purchases: int
    revenue_per_1000: Optional[float] = None
    proceeds: Optional[float] = None
    net_revenue: Optional[float] = None
    probability: Optional[float] = None

    @property
    def conversion_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        return (float(self.purchases) / float(self.views)) * 100.0


@dataclass(frozen=True)
class AdaptyAbMetrics:
    test_id: str
    test_name: str
    variants: tuple[AdaptyAbVariantMetrics, AdaptyAbVariantMetrics]
    collected_at: datetime


def normalize_dashboard_authorization(token: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        raise AdaptyDashboardError("Adapty dashboard authentication token is missing")
    if raw.lower().startswith("bearer "):
        return f"Bearer {raw.split(None, 1)[1].strip()}"
    return f"Bearer {raw}"


def _alias(data: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptyDashboardError(f"Adapty dashboard response is missing {context}")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise AdaptyDashboardError(f"Adapty dashboard response is missing {context}")
    return value


def _identifier(data: Mapping[str, Any], context: str, *names: str) -> str:
    value = _alias(data, *names)
    result = str(value or "").strip()
    if not result:
        raise AdaptyDashboardError(f"Adapty dashboard response is missing {context}")
    return result


def _number(data: Mapping[str, Any], context: str, *names: str) -> float:
    value = _alias(data, *names)
    if isinstance(value, Mapping):
        value = _alias(value, "value", "total")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise AdaptyDashboardError(f"Adapty dashboard response is missing {context}")


def _optional_number(data: Mapping[str, Any], *names: str) -> Optional[float]:
    value = _alias(data, *names)
    if isinstance(value, Mapping):
        value = _alias(value, "value", "total")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_name(value: str) -> str:
    return " ".join(value.split())


class AdaptyAbDashboardClient:
    def __init__(
        self,
        app_id: str,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: int = 30,
    ) -> None:
        self.app_id = str(app_id or "").strip()
        if not self.app_id:
            raise AdaptyDashboardError("Adapty dashboard app ID is missing")
        self.authorization = normalize_dashboard_authorization(token)
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get_json(
        self,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
    ) -> Mapping[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                headers={
                    "Authorization": self.authorization,
                    "Accept": "application/json",
                },
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as err:
            raise AdaptyDashboardError(
                f"Adapty dashboard request failed ({type(err).__name__})"
            ) from err

        status = int(response.status_code)
        if status in (401, 403):
            raise AdaptyDashboardError("Adapty dashboard authentication failed")
        if status >= 400:
            raise AdaptyDashboardError(
                f"Adapty dashboard request failed with status {status}"
            )
        try:
            payload = response.json()
        except ValueError as err:
            raise AdaptyDashboardError(
                "Adapty dashboard returned invalid JSON"
            ) from err
        return _object(payload, "JSON object")

    def fetch_metrics(
        self,
        test_id: str,
        expected_test_name: str,
        expected_variants: Mapping[str, tuple[str, str]],
    ) -> AdaptyAbMetrics:
        requested_test_id = str(test_id or "").strip()
        if not requested_test_id:
            raise AdaptyDashboardError("Adapty A/B test ID is missing")

        metadata_payload = self._get_json(
            f"portal/{self.app_id}/in-apps/ab-tests/{requested_test_id}/"
        )
        metadata_value = metadata_payload.get("data", metadata_payload)
        metadata = _object(metadata_value, "experiment metadata")
        actual_test_id = _identifier(
            metadata,
            "experiment ID",
            "ab_test_id",
            "abTestId",
            "id",
        )
        if actual_test_id != requested_test_id:
            raise AdaptyDashboardError("Adapty dashboard experiment ID mismatch")

        actual_test_name = _identifier(
            metadata,
            "experiment name",
            "title",
            "name",
            "ab_test_name",
            "abTestName",
        )
        if _normalized_name(actual_test_name) != _normalized_name(expected_test_name):
            raise AdaptyDashboardError("Adapty dashboard experiment name mismatch")

        paywalls = _list(metadata.get("paywalls"), "experiment variants")
        if len(paywalls) != 2:
            raise AdaptyDashboardError("Adapty dashboard must return exactly two variants")

        variant_metadata: list[tuple[str, str, str]] = []
        seen_paywall_ids: set[str] = set()
        for index, entry_value in enumerate(paywalls):
            entry = _object(entry_value, f"variant {index + 1}")
            paywall_value = entry.get("paywall", entry)
            paywall = _object(paywall_value, f"variant {index + 1} paywall")
            paywall_id = _identifier(
                paywall,
                f"variant {index + 1} paywall ID",
                "paywall_id",
                "paywallId",
                "id",
            )
            paywall_name = _identifier(
                paywall,
                f"variant {index + 1} paywall name",
                "title",
                "name",
                "paywall_name",
                "paywallName",
            )
            if paywall_id in seen_paywall_ids:
                raise AdaptyDashboardError("Adapty dashboard returned duplicate paywalls")
            seen_paywall_ids.add(paywall_id)
            label = chr(ord("A") + index)
            expected = expected_variants.get(label)
            if expected is None:
                raise AdaptyDashboardError(f"Configured variant {label} is missing")
            expected_id, expected_name = expected
            if paywall_id != expected_id or _normalized_name(paywall_name) != _normalized_name(
                expected_name
            ):
                raise AdaptyDashboardError(
                    f"Adapty dashboard variant {label} does not match configuration"
                )
            variant_metadata.append((label, paywall_id, _normalized_name(paywall_name)))

        metrics_payload = self._get_json(
            f"portal/{self.app_id}/analytics/ab-tests/metrics/",
            params={"filter[ab_test_id]": requested_test_id},
        )
        tests = _list(metrics_payload.get("data"), "experiment metrics")
        matching_tests = []
        for item_value in tests:
            item = _object(item_value, "experiment metrics item")
            item_test_id = str(_alias(item, "ab_test_id", "abTestId") or "").strip()
            if item_test_id == requested_test_id:
                matching_tests.append(item)
        if len(matching_tests) != 1:
            raise AdaptyDashboardError(
                "Adapty dashboard did not return exactly one matching experiment"
            )

        metric_items = _list(matching_tests[0].get("items"), "variant metrics")
        metrics_by_paywall: dict[str, Mapping[str, Any]] = {}
        for item_value in metric_items:
            item = _object(item_value, "variant metrics item")
            paywall_id = _identifier(
                item,
                "variant metrics paywall ID",
                "paywall_id",
                "paywallId",
            )
            if paywall_id in metrics_by_paywall:
                raise AdaptyDashboardError("Adapty dashboard returned duplicate variant metrics")
            metrics_by_paywall[paywall_id] = item

        variants: list[AdaptyAbVariantMetrics] = []
        for label, paywall_id, paywall_name in variant_metadata:
            metric = metrics_by_paywall.get(paywall_id)
            if metric is None:
                raise AdaptyDashboardError(
                    f"Adapty dashboard metrics are missing variant {label}"
                )
            variants.append(
                AdaptyAbVariantMetrics(
                    label=label,
                    paywall_id=paywall_id,
                    paywall_name=paywall_name,
                    revenue=_number(metric, f"variant {label} revenue", "revenue"),
                    arpas=_number(metric, f"variant {label} arpas", "arpas"),
                    views=int(_number(metric, f"variant {label} views", "views")),
                    purchases=int(
                        _number(metric, f"variant {label} purchases", "purchases")
                    ),
                    revenue_per_1000=_optional_number(
                        metric,
                        "average_per_1000",
                        "averagePer1000",
                        "revenue_per_1000",
                        "revenuePer1000",
                    ),
                    proceeds=_optional_number(metric, "proceeds"),
                    net_revenue=_optional_number(
                        metric,
                        "net_revenue",
                        "netRevenue",
                        "net_proceeds",
                        "netProceeds",
                    ),
                    probability=_optional_number(metric, "probability"),
                )
            )

        logger.info("Collected validated Adapty A/B dashboard metrics")
        return AdaptyAbMetrics(
            test_id=actual_test_id,
            test_name=_normalized_name(actual_test_name),
            variants=(variants[0], variants[1]),
            collected_at=datetime.now(timezone.utc),
        )
