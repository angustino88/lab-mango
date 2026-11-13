"""URL module aggregator for the labs app."""
from django.urls import include, path

urlpatterns = [
    path("labs/", include("core.labs.features.equipment.urls")),
    path("labs/", include("core.labs.features.licenses.urls")),
    path("labs/", include("core.labs.features.benches.urls")),
    path("labs/", include("core.labs.features.bench_bookings.urls")),
    path("labs/", include("core.labs.features.locations.urls")),
    path("labs/", include("core.labs.features.downtime.urls")),
    path("labs/", include("core.labs.features.procurement.urls")),
    path("labs/", include("core.labs.features.expense.urls")),
    path("labs/", include("core.labs.features.resource_audit.urls")),
    # path("labs/", include("core.labs.features.lab_management.urls")),
    # path("labs/", include("core.labs.features.booking.urls")),
    path("labs/", include("core.labs.features.monitoring.urls")),
    path("labs/", include("core.labs.features.leaderboard.urls")),
    path("labs/analytics/", include("core.labs.features.analytics.urls")),
    path("labs/", include("core.labs.features.dashboard.urls")),
    path("labs/", include("core.labs.features.resource_mappings.urls")),
]
