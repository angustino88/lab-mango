"""Location routes: station, room, and geographic catalog endpoint sets combined under the feature root (ADR 002)."""

from django.urls import path

from core.labs.features.locations.rooms.api.urls import urlpatterns as room_urlpatterns
from core.labs.features.locations.stations.api.urls import urlpatterns as station_urlpatterns

from . import geo_views
from .reference_data import urlpatterns as reference_urlpatterns

geo_urlpatterns = [
    # Countries
    path("countries", geo_views.CountryListAPIView.as_view(), name="country-list"),
    path("countries/options", geo_views.CountryOptionsAPIView.as_view(), name="country-options"),
    path("countries/<int:country_id>", geo_views.CountryDetailAPIView.as_view(), name="country-detail"),

    # Cities
    path("cities", geo_views.CityListAPIView.as_view(), name="city-list"),
    path("cities/options", geo_views.CityOptionsAPIView.as_view(), name="city-options"),
    path("cities/<int:city_id>", geo_views.CityDetailAPIView.as_view(), name="city-detail"),

    # Buildings
    path("buildings", geo_views.BuildingListAPIView.as_view(), name="building-list"),
    path("buildings/options", geo_views.BuildingOptionsAPIView.as_view(), name="building-options"),
    path("buildings/<int:building_id>", geo_views.BuildingDetailAPIView.as_view(), name="building-detail"),
]

urlpatterns = [*station_urlpatterns, *room_urlpatterns, *geo_urlpatterns, *reference_urlpatterns]
