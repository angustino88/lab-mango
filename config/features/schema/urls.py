from django.urls import path
from drf_api_contracts import ResponseContract
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from drf_spectacular.views import SpectacularAPIView


@extend_schema_view(
    get=extend_schema(
        tags=["Schema"],
        summary="Get OpenAPI Schema",
        description="Retrieve the OpenAPI contract. Select YAML or JSON through content negotiation or the format query parameter.",
        responses={
            200: OpenApiTypes.OBJECT,
            **{
                (status_code, media_type): OpenApiResponse(
                    response=ResponseContract.problem(status_code).schema,
                    description=description,
                )
                for status_code, description in (
                    (401, "Missing or invalid credentials; includes WWW-Authenticate."),
                    (403, "Authenticated user is not a staff user (IsAdminUser)."),
                )
                # The inherited renderers negotiate error envelopes too; do not
                # claim JSON-only errors or wrap the OpenAPI success document.
                for media_type in (
                    "application/vnd.oai.openapi",
                    "application/yaml",
                    "application/vnd.oai.openapi+json",
                    "application/json",
                )
            },
        },
    )
)
class SchemaAPIView(SpectacularAPIView):
    """Own schema metadata without modifying the third-party view class."""


urlpatterns = [
    path("", SchemaAPIView.as_view(), name="api-schema"),
]
