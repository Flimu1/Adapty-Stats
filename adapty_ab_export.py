"""Strict client for experiment-scoped Adapty Analytics Export metrics."""
from dataclasses import dataclass
from datetime import date
import math
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AdaptyAbExportError(RuntimeError):
    """The Export API did not return usable A/B metrics."""


class _MinimumBackoffRetry(Retry):
    """Ensure the first automatic retry is paced when Retry-After is absent."""

    def get_backoff_time(self) -> float:
        backoff = super().get_backoff_time()
        return 0.55 if self.history and backoff < 0.55 else backoff


@dataclass(frozen=True)
class AdaptyAbVariantMetrics:
    label: str
    paywall_id: str
    revenue: float
    unique_views: int
    purchases: int
    arpas: float

    @property
    def conversion_rate(self) -> float:
        return 0.0 if self.unique_views == 0 else self.purchases / self.unique_views * 100


class AdaptyAbExportClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api-admin.adapty.io",
        analytics_path: str = "api/v1/client-api/metrics/analytics/",
        timezone: str = "Europe/Minsk",
        session: requests.Session | None = None,
        request_interval: float = 0.55,
    ) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/{analytics_path.lstrip('/')}"
        self._timezone = timezone
        self._session = session or self._new_session()
        self._request_interval = request_interval

    @staticmethod
    def _new_session() -> requests.Session:
        session = requests.Session()
        retry = _MinimumBackoffRetry(
            total=3,
            backoff_factor=0.55,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch_variant(
        self,
        *,
        label: str,
        paywall_id: str,
        test_id: str,
        start_date: date,
        end_date: date,
    ) -> AdaptyAbVariantMetrics:
        revenue_payload = self._fetch_chart(
            "revenue", paywall_id, test_id, start_date, end_date
        )
        conversion_payload = self._fetch_chart(
            "paywall_view_paid", paywall_id, test_id, start_date, end_date
        )
        refund_payload = self._fetch_chart(
            "refund_events", paywall_id, test_id, start_date, end_date
        )
        revenue = _nonnegative_float(
            _required_value(revenue_payload, ("data", "revenue", "value"))
        )
        unique_views = _nonnegative_int(
            _required_value(conversion_payload, ("data", "common", "value_from"))
        )
        paid_profiles = _nonnegative_int(
            _required_value(conversion_payload, ("data", "common", "value_to"))
        )
        refunds = _nonnegative_int(
            _required_value(refund_payload, ("data", "common", "value"))
        )
        purchases = paid_profiles + refunds
        if unique_views == 0 and purchases > 0:
            raise AdaptyAbExportError(
                "Adapty Export returned purchases without unique views"
            )
        arpas = 0.0 if purchases == 0 else revenue / purchases
        return AdaptyAbVariantMetrics(
            label, paywall_id, revenue, unique_views, purchases, arpas
        )

    def _fetch_chart(
        self,
        chart_id: str,
        paywall_id: str,
        test_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        body = {
            "chart_id": chart_id,
            "filters": {
                "date": [start_date.isoformat(), end_date.isoformat()],
                "paywall_id": [paywall_id],
                "placement_audience_version_id": [test_id],
            },
            "period_unit": "day",
            "date_type": "purchase_date",
            "format": "json",
        }
        try:
            response = self._session.post(
                self._url,
                json=body,
                headers={
                    "Authorization": f"Api-Key {self._api_key}",
                    "Content-Type": "application/json",
                    "Adapty-Tz": self._timezone,
                },
                timeout=30,
            )
        except requests.RequestException as error:
            raise AdaptyAbExportError("Adapty Export request failed") from None
        status = response.status_code
        if status in (401, 403):
            raise AdaptyAbExportError("Adapty Export authentication failed")
        if status == 429 or 500 <= status <= 599:
            raise AdaptyAbExportError("Adapty Export is temporarily unavailable")
        if not 200 <= status <= 299:
            raise AdaptyAbExportError("Adapty Export request failed")
        if self._request_interval:
            time.sleep(self._request_interval)
        try:
            return response.json()
        except ValueError as error:
            raise AdaptyAbExportError("Adapty Export returned invalid JSON") from None


def _required_value(payload: object, path: tuple[str, ...]) -> object:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise AdaptyAbExportError("Adapty Export response is missing a required metric")
        current = current[key]
    return current


def _nonnegative_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdaptyAbExportError("Adapty Export returned an invalid metric value")
    try:
        number = float(value)
    except OverflowError:
        raise AdaptyAbExportError("Adapty Export returned an invalid metric value") from None
    if not math.isfinite(number):
        raise AdaptyAbExportError("Adapty Export returned an invalid metric value")
    if number < 0:
        raise AdaptyAbExportError("Adapty Export returned a negative metric value")
    return number


def _nonnegative_int(value: object) -> int:
    number = _nonnegative_float(value)
    if not number.is_integer():
        raise AdaptyAbExportError("Adapty Export returned a fractional count")
    return int(number)
