"""Resource lookup HTTP adapter."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base import BENCH_BOOKING_ACCESS, FeatureAPIView
from core.labs.features.resource_lookup.queries import lookup_resources

from .serializers import ResourceLookupMatchSerializer, ResourceLookupQuerySerializer


class ResourceLookupAPIView(FeatureAPIView):
    """Every Labs role may ask; each type is searched only if the caller may read it."""

    permission_classes = BENCH_BOOKING_ACCESS
    schema_tags = ("Resource Lookup",)
    get_contract = OperationContract(
        query=ResourceLookupQuerySerializer,
        success=ResponseContract.success("ResourceLookup", ResourceLookupMatchSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        filters = dict(filters or {})
        matches = lookup_resources(
            actor=request.user, q=filters["q"], types=tuple(filters.get("types") or ()), limit=filters["limit"]
        )
        return self.respond(matches, many=True)
