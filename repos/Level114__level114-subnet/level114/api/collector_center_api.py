"""Collector Center API client."""

from ._collector_center_base import _CollectorCenterBase
from ._collector_center_metrics import _ServerMetricsMixin
from ._collector_center_reports import _ServerReportsMixin
from ._collector_center_servers import _ServerCatalogMixin
from ._collector_center_validators import _ValidatorEndpointsMixin

__all__ = ["CollectorCenterAPI"]


class CollectorCenterAPI(
    _CollectorCenterBase,
    _ValidatorEndpointsMixin,
    _ServerCatalogMixin,
    _ServerMetricsMixin,
    _ServerReportsMixin,
):
    """Simple client for interacting with Collector-Center service."""

    pass
