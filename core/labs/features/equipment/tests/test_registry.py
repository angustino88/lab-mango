from django.urls.resolvers import URLPattern, URLResolver

from core.labs.features.equipment.api.registry import (
    EQUIPMENT_API_REGISTRY,
    EQUIPMENT_REGISTRY,
    get_equipment_urlpatterns,
)
from core.labs.models import Equipment


def test_registered_equipment_definitions_have_valid_model_fields():
    for definition in EQUIPMENT_REGISTRY.values():
        model_fields = {field.name for field in definition.model._meta.fields}
        assert {"sku", definition.display_field} <= model_fields
        assert issubclass(definition.model, Equipment)


def test_registry_builds_every_equipment_url_module():
    patterns = get_equipment_urlpatterns()

    assert patterns
    assert all(isinstance(pattern, (URLPattern, URLResolver)) for pattern in patterns)
    assert {definition.public_key for definition in EQUIPMENT_REGISTRY.values()} == set(EQUIPMENT_API_REGISTRY)


def test_registry_contains_all_api_category_models():
    from core.labs.features.equipment.api.category_definitions import CATEGORY_DEFINITIONS

    assert set(CATEGORY_DEFINITIONS) <= set(EQUIPMENT_REGISTRY)
    for key, definition in CATEGORY_DEFINITIONS.items():
        assert EQUIPMENT_REGISTRY[key].model is definition.model

