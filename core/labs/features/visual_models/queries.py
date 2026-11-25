from django.db.models import Count

from core.labs.models.visual_models import VisualModelAsset, VisualModelAssignment


def list_assets():
    return VisualModelAsset.objects.annotate(usage_count=Count("assignments"))


def get_asset(asset_id: int):
    return list_assets().filter(pk=asset_id).first()


def list_assignments():
    return VisualModelAssignment.objects.all()
