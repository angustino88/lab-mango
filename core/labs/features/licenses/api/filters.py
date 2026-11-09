"""License inventory extension of the shared resource filters."""

from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models import LicenseStatus

LICENSE_FILTERS = resource_filter_spec(
    search_fields=("sku", "name", "product__name", "vendor__name"),
    status_choices=LicenseStatus.choices,
)
