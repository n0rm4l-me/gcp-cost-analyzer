"""Idle and underutilized GCP resource detector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import subprocess
import datetime
from googleapiclient import discovery
import google.oauth2.credentials
import google_auth_httplib2
import httplib2


def _get_token() -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _rest_client(service: str, version: str):
    token = _get_token()
    creds = google.oauth2.credentials.Credentials(token=token)
    http = httplib2.Http(disable_ssl_certificate_validation=True)
    authed = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return discovery.build(service, version, http=authed)


@dataclass
class IdleDisk:
    name: str
    project: str
    zone: str
    size_gb: int
    disk_type: str
    estimated_monthly_cost: float

    @property
    def description(self) -> str:
        return f"`{self.name}` ({self.zone}, {self.size_gb}GB {self.disk_type}) — ~${self.estimated_monthly_cost:.0f}/mo"


@dataclass
class IdleSnapshot:
    name: str
    project: str
    size_gb: int
    age_days: int
    estimated_monthly_cost: float

    @property
    def description(self) -> str:
        return f"`{self.name}` ({self.size_gb}GB, {self.age_days}d old) — ~${self.estimated_monthly_cost:.0f}/mo"


@dataclass
class UnderutilizedNodePool:
    cluster: str
    node_pool: str
    project: str
    zone: str
    avg_cpu_pct: float
    avg_mem_pct: float
    node_count: int

    @property
    def description(self) -> str:
        return (
            f"`{self.cluster}/{self.node_pool}` ({self.node_count} nodes) — "
            f"avg CPU {self.avg_cpu_pct:.1f}%, mem {self.avg_mem_pct:.1f}%"
        )


@dataclass
class ResourceReport:
    project_id: str
    idle_disks: list[IdleDisk] = field(default_factory=list)
    idle_snapshots: list[IdleSnapshot] = field(default_factory=list)
    underutilized_node_pools: list[UnderutilizedNodePool] = field(default_factory=list)

    @property
    def total_waste_estimate(self) -> float:
        disk_waste = sum(d.estimated_monthly_cost for d in self.idle_disks)
        snap_waste = sum(s.estimated_monthly_cost for s in self.idle_snapshots)
        return disk_waste + snap_waste

    @property
    def has_findings(self) -> bool:
        return bool(self.idle_disks or self.idle_snapshots or self.underutilized_node_pools)


# Approximate GCP pricing (USD/GB/month)
_DISK_PRICE = {"pd-standard": 0.04, "pd-ssd": 0.17, "pd-balanced": 0.10}
_SNAPSHOT_PRICE = 0.026


def detect_idle_disks(project_id: str) -> list[IdleDisk]:
    """Find persistent disks not attached to any instance."""
    idle = []
    try:
        svc = _rest_client("compute", "v1")
        request = svc.disks().aggregatedList(project=project_id)
        while request is not None:
            response = request.execute()
            for zone_name, zone_data in response.get("items", {}).items():
                for disk in zone_data.get("disks", []):
                    if not disk.get("users"):
                        zone = zone_name.replace("zones/", "")
                        disk_type = disk.get("type", "").split("/")[-1] or "pd-standard"
                        price_per_gb = _DISK_PRICE.get(disk_type, 0.04)
                        size_gb = int(disk.get("sizeGb", 0))
                        idle.append(IdleDisk(
                            name=disk["name"],
                            project=project_id,
                            zone=zone,
                            size_gb=size_gb,
                            disk_type=disk_type,
                            estimated_monthly_cost=size_gb * price_per_gb,
                        ))
            request = svc.disks().aggregatedList_next(request, response)
    except Exception:
        pass
    return idle


def detect_idle_snapshots(project_id: str, max_age_days: int = 90) -> list[IdleSnapshot]:
    """Find snapshots older than max_age_days."""
    idle = []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
    try:
        svc = _rest_client("compute", "v1")
        request = svc.snapshots().list(project=project_id)
        while request is not None:
            response = request.execute()
            for snap in response.get("items", []):
                created = datetime.datetime.fromisoformat(
                    snap["creationTimestamp"].replace("Z", "+00:00")
                )
                if created < cutoff:
                    age_days = (datetime.datetime.now(datetime.timezone.utc) - created).days
                    storage_bytes = int(snap.get("storageBytes", 0))
                    size_gb = storage_bytes // (1024 ** 3)
                    idle.append(IdleSnapshot(
                        name=snap["name"],
                        project=project_id,
                        size_gb=size_gb,
                        age_days=age_days,
                        estimated_monthly_cost=size_gb * _SNAPSHOT_PRICE,
                    ))
            request = svc.snapshots().list_next(request, response)
    except Exception:
        pass
    return sorted(idle, key=lambda s: s.age_days, reverse=True)


def detect_underutilized_node_pools(
    project_id: str,
    cpu_threshold: float = 20.0,
    mem_threshold: float = 30.0,
    lookback_days: int = 7,
) -> list[UnderutilizedNodePool]:
    """Find GKE node pools with consistently low CPU via Cloud Monitoring REST API."""
    underutilized = []
    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = now - datetime.timedelta(days=lookback_days)

    try:
        svc = _rest_client("monitoring", "v3")
        cpu_filter = (
            'metric.type="kubernetes.io/node/cpu/allocatable_utilization" '
            f'resource.labels.project_id="{project_id}"'
        )
        response = svc.projects().timeSeries().list(
            name=f"projects/{project_id}",
            filter=cpu_filter,
            interval_startTime=start_time.isoformat(),
            interval_endTime=now.isoformat(),
            view="FULL",
        ).execute()

        cpu_results: dict[str, list[float]] = {}
        for ts in response.get("timeSeries", []):
            labels = ts.get("resource", {}).get("labels", {})
            cluster = labels.get("cluster_name", "unknown")
            node_pool = labels.get("node_pool_name", "unknown")
            key = f"{cluster}/{node_pool}"
            values = [
                p["value"].get("doubleValue", 0) * 100
                for p in ts.get("points", [])
            ]
            if values:
                cpu_results.setdefault(key, []).extend(values)

        for key, values in cpu_results.items():
            avg_cpu = sum(values) / len(values)
            if avg_cpu < cpu_threshold:
                cluster, node_pool = key.split("/", 1)
                underutilized.append(UnderutilizedNodePool(
                    cluster=cluster,
                    node_pool=node_pool,
                    project=project_id,
                    zone="multi-zone",
                    avg_cpu_pct=avg_cpu,
                    avg_mem_pct=0.0,
                    node_count=0,
                ))
    except Exception:
        pass
    return underutilized


def analyze_resources(project_id: str) -> ResourceReport:
    return ResourceReport(
        project_id=project_id,
        idle_disks=detect_idle_disks(project_id),
        idle_snapshots=detect_idle_snapshots(project_id),
        underutilized_node_pools=detect_underutilized_node_pools(project_id),
    )
