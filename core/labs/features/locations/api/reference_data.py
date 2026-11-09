"""Location-owned geographic import declarations."""

from core.common.api.reference_views import reference_urlpatterns
from core.labs.models import Building, City, Country, StationType
from core.reference_data.contracts import ReferenceResource

from ..application.reference_data import create_catalog_reference
from ..queries import get_catalog_reference, list_catalog_references

RESOURCES = (
    ("countries", Country, ("name", "code"), ("code",)),
    ("cities", City, ("name", "country"), ("country_id", "name")),
    ("buildings", Building, ("name", "city", "address"), ("city_id", "name")),
    ("station-types", StationType, ("name",), ("name",)),
)
urlpatterns = []
for segment, model, fields, identity in RESOURCES:
    urlpatterns += reference_urlpatterns(
        resource=ReferenceResource(f"location-reference-{segment}", model, fields, identity),
        prefix=f"locations/reference-data/{segment}",
        tag="Locations",
        module=__name__,
        create=create_catalog_reference,
        listing=list_catalog_references,
        retrieve=get_catalog_reference,
    )
