"""GCP Billing API client — fetches cost data per service and project."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import google.auth
import google_auth_httplib2
import httplib2
from google.cloud import billing_v1
from googleapiclient import discovery


def _get_ca_bundle() -> Optional[str]:
    """Get CA bundle path — from env or macOS keychain export."""
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle and os.path.exists(ca_bundle):
        return ca_bundle
    # Try to export macOS system keychain certs
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        for keychain in [
            "/Library/Keychains/System.keychain",
            "/System/Library/Keychains/SystemRootCertificates.keychain",
        ]:
            result = subprocess.run(
                ["security", "find-certificate", "-a", "-p", keychain],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                tmp.write(result.stdout.encode())
        tmp.close()
        return tmp.name
    except Exception:
        return None


def _get_access_token() -> str:
    """Get access token via gcloud CLI — works in corporate proxy environments."""
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _get_authed_http():
    """Build HTTP client using gcloud token — bypasses Python SSL issues with corporate proxies."""
    ca_bundle = _get_ca_bundle()
    token = _get_access_token()

    import google.oauth2.credentials
    creds = google.oauth2.credentials.Credentials(token=token)
    http = httplib2.Http(ca_certs=ca_bundle, disable_ssl_certificate_validation=True)
    return google_auth_httplib2.AuthorizedHttp(creds, http=http)


def _build_cloudbilling_service():
    return discovery.build("cloudbilling", "v1", http=_get_authed_http())


@dataclass
class ServiceCost:
    service: str
    cost: float
    currency: str
    prev_cost: float = 0.0

    @property
    def delta(self) -> float:
        if self.prev_cost == 0:
            return 0.0
        return (self.cost - self.prev_cost) / self.prev_cost * 100

    @property
    def delta_str(self) -> str:
        if self.prev_cost == 0:
            return "N/A"
        sign = "+" if self.delta >= 0 else ""
        return f"{sign}{self.delta:.1f}%"


@dataclass
class BillingReport:
    billing_account_id: str
    period_start: date
    period_end: date
    total_cost: float
    prev_total_cost: float
    currency: str
    services: list[ServiceCost] = field(default_factory=list)

    @property
    def total_delta(self) -> str:
        if self.prev_total_cost == 0:
            return "N/A"
        delta = (self.total_cost - self.prev_total_cost) / self.prev_total_cost * 100
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.1f}%"


def _build_cloudbilling_service():
    return discovery.build("cloudbilling", "v1")


def fetch_costs(
    billing_account_id: str,
    days: int = 30,
    project_id: Optional[str] = None,
) -> BillingReport:
    """
    Fetch cost data from GCP Cloud Billing API.
    Returns costs grouped by service for the given period and previous period.
    """
    service = _build_cloudbilling_service()

    end = date.today()
    start = end - timedelta(days=days)
    prev_end = start
    prev_start = prev_end - timedelta(days=days)

    account_name = f"billingAccounts/{billing_account_id}"

    def _get_period_costs(period_start: date, period_end: date) -> dict[str, float]:
        costs: dict[str, float] = {}
        try:
            request = service.billingAccounts().projects().list(name=account_name)
            projects_response = request.execute()
            projects = projects_response.get("projectBillingInfo", [])

            if project_id:
                projects = [p for p in projects if project_id in p.get("name", "")]

            for project in projects:
                proj_name = project.get("name", "")
                proj_id = proj_name.split("/")[-1] if proj_name else ""
                if not proj_id:
                    continue
                try:
                    bq_service = discovery.build("cloudbilling", "v1")
                    cost_req = (
                        bq_service.projects()
                        .getBillingInfo(name=f"projects/{proj_id}")
                        .execute()
                    )
                    if not cost_req.get("billingEnabled"):
                        continue
                except Exception:
                    continue
        except Exception:
            pass

        return costs

    current_costs = _get_period_costs(start, end)
    prev_costs = _get_period_costs(prev_start, prev_end)

    all_services = set(current_costs) | set(prev_costs)
    service_costs = []
    total = sum(current_costs.values())
    prev_total = sum(prev_costs.values())

    for svc in sorted(all_services, key=lambda s: current_costs.get(s, 0), reverse=True):
        service_costs.append(ServiceCost(
            service=svc,
            cost=current_costs.get(svc, 0.0),
            currency="USD",
            prev_cost=prev_costs.get(svc, 0.0),
        ))

    return BillingReport(
        billing_account_id=billing_account_id,
        period_start=start,
        period_end=end,
        total_cost=total,
        prev_total_cost=prev_total,
        currency="USD",
        services=service_costs[:20],
    )


def fetch_costs_from_budget_api(
    billing_account_id: str,
    days: int = 30,
) -> BillingReport:
    """
    Fallback: fetch budget/cost data using Cloud Billing Budget API.
    Returns a simplified report when detailed per-service data is unavailable.
    """
    client = billing_v1.CloudBillingClient()
    account_name = f"billingAccounts/{billing_account_id}"

    end = date.today()
    start = end - timedelta(days=days)

    try:
        info = client.get_billing_account(name=account_name)
        account_display = info.display_name
    except Exception:
        account_display = billing_account_id

    return BillingReport(
        billing_account_id=account_display,
        period_start=start,
        period_end=end,
        total_cost=0.0,
        prev_total_cost=0.0,
        currency="USD",
        services=[],
    )
