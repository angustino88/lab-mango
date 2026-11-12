from core.common.admin import LabMangoModelAdmin


class ProtectedReferenceAdmin(LabMangoModelAdmin):
    """Admin policy that disables instance and bulk deletion."""

    actions = None

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


__all__ = ["ProtectedReferenceAdmin"]
