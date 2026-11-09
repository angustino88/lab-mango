"""URL patterns for resource auditing API endpoints by ID, SKU, and UID."""

from django.urls import path

from . import views

urlpatterns = [
    # Explicit identifier routes for resource audits
    path(
        "resources/id/<int:resource_id>/audits",
        views.ResourceAuditByIdView.as_view(),
        name="resource-audit-by-id",
    ),
    path(
        "resources/sku/<str:sku>/audits",
        views.ResourceAuditBySkuView.as_view(),
        name="resource-audit-by-sku",
    ),
    path(
        "resources/uid/<uuid:uid>/audits",
        views.ResourceAuditByUidView.as_view(),
        name="resource-audit-by-uid",
    ),
    # Resource type + identifier collection
    path(
        "resources/<str:resource_type>/<str:resource_id>/audits",
        views.TypedResourceAuditListCreateView.as_view(),
        name="typed-resource-audit-list-create",
    ),
    # Global audit log and detail
    path(
        "audits",
        views.AllResourceAuditListAPIView.as_view(),
        name="resource-audit-all-list",
    ),
    path(
        "audits/<int:audit_id>",
        views.ResourceAuditDetailAPIView.as_view(),
        name="resource-audit-detail",
    ),
]
