from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from core.reference_data.models import ProtectedReferenceMixin


@receiver(pre_delete, dispatch_uid="reference_data.protect_ensured_rows")
def prevent_protected_reference_cascade(*, instance, **kwargs) -> None:
    """Reject deletion collectors attempting to cascade through protected rows."""
    if isinstance(instance, ProtectedReferenceMixin):
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")
