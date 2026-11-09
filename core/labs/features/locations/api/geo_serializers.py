"""Geographic catalog and options serializers (ADR 002)."""

from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.labs.features.base.serializers import AppModelSerializer
from core.labs.models import Building, City, Country


class CountrySerializer(AppModelSerializer):
    class Meta:
        model = Country
        fields = ("id", "code", "name")
        ref_name = "CountryCatalogItem"


class CitySerializer(AppModelSerializer):
    country = CountrySerializer(read_only=True)
    country_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = City
        fields = ("id", "name", "country", "country_id")
        ref_name = "CityCatalogItem"


class BuildingSerializer(AppModelSerializer):
    city = CitySerializer(read_only=True)
    city_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = Building
        fields = ("id", "name", "address", "city", "city_id")
        ref_name = "BuildingCatalogItem"


class CityOptionsQuerySerializer(OptionsQueryMixin):
    country_id = serializers.IntegerField(required=False, min_value=1)


class BuildingOptionsQuerySerializer(OptionsQueryMixin):
    city_id = serializers.IntegerField(required=False, min_value=1)


__all__ = [
    "BuildingOptionsQuerySerializer",
    "BuildingSerializer",
    "CityOptionsQuerySerializer",
    "CitySerializer",
    "CountrySerializer",
]
