"""Explicit retry-safe import routes, preserving legacy bench lookup routes."""

from core.common.api.reference_views import reference_urlpatterns
from core.labs.models import BenchGroup, BenchType
from core.reference_data.contracts import ReferenceResource

from ..application.reference_data import create_catalog_reference
from ..queries.reference_data import get_catalog_reference, list_catalog_references

urlpatterns = []
for segment, model in (("groups", BenchGroup), ("types", BenchType)):
    urlpatterns += reference_urlpatterns(
        resource=ReferenceResource(f"bench-reference-{segment}", model, ("name", "active"), ("name",)),
        prefix=f"benches/reference-data/{segment}",
        tag="Benches",
        module=__name__,
        create=create_catalog_reference,
        listing=list_catalog_references,
        retrieve=get_catalog_reference,
    )
