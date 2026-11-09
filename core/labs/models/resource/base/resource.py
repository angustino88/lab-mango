import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from model_utils.models import TimeStampedModel

from core.common.models import TimestampedSoftDeleteMixin, UserStampedModel
from core.infrastructure.storage.uploads import ResourceImageUploadPath


class Department(TimeStampedModel, UserStampedModel):
    """Organisation unit that owns resources (e.g. ADAS Validation)."""

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    active = models.BooleanField(default=True, db_index=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(condition=~Q(name=""), name="department_name_not_empty"),
        ]


class ResourceGroup(TimeStampedModel, UserStampedModel):
    """Team inside a department. Not to be confused with BenchGroup (function)."""

    name = models.CharField(max_length=255, unique=True)
    department = models.ForeignKey(
        "labs.Department",
        related_name="groups",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True, default="")
    active = models.BooleanField(default=True, db_index=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)


class ResourceModel(TimeStampedModel, UserStampedModel, TimestampedSoftDeleteMixin):
    """Common identity, ownership, lifecycle, and audit behavior for resources."""

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sku = models.CharField(max_length=255)
    name = models.CharField(
        max_length=255,
        db_index=True,
        blank=True,
        default="",
    )
    department = models.ForeignKey(
        "labs.Department",
        related_name="%(app_label)s_%(class)s_department_resources",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Owning department.",
    )
    group = models.ForeignKey(
        "labs.ResourceGroup",
        related_name="%(app_label)s_%(class)s_resources",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Owning team; must belong to the selected department.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_owned_resources",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    remark = models.CharField(max_length=255, blank=True, default="")
    image = models.ImageField(
        upload_to=ResourceImageUploadPath(),
        null=True,
        blank=True,
    )

    def clean(self) -> None:
        super().clean()
        self.sku = self.sku.strip()
        self.name = self.name.strip()
        self.remark = self.remark.strip()
        if not self.sku:
            raise ValidationError({"sku": "SKU cannot be blank."})
        if self.group_id:
            group_department_id = self.group.department_id
            if self.department_id is None and group_department_id:
                self.department_id = group_department_id
            elif (
                group_department_id
                and self.department_id
                and group_department_id != self.department_id
            ):
                raise ValidationError({"group": "The group belongs to a different department."})

    def save(self, *args, **kwargs):
        self.sku = self.sku.strip()
        self.name = self.name.strip()
        self.remark = self.remark.strip()
        # The database enforces relational and constraint integrity. Avoid
        # issuing one lookup per FK plus duplicate/constraint queries on saves.
        excluded_relations = [
            field.name for field in self._meta.concrete_fields if field.is_relation
        ]
        self.full_clean(
            exclude=excluded_relations,
            validate_unique=False,
            validate_constraints=False,
        )
        return super().save(*args, **kwargs)

    @property
    def audits(self):
        """Return this resource's audits newest first."""
        from core.labs.models.auditing.resource_audit import ResourceAudit

        return ResourceAudit.objects.for_resource(self)

    @property
    def service_records(self):
        """Calibration, inspection, maintenance and safety-test history, newest first."""
        from core.labs.models.resource.base.service_record import ResourceServiceRecord

        return ResourceServiceRecord.objects.for_resource(self)

    def latest_service_record(self, kind: str):
        """Return the most recent service record of ``kind`` or None."""
        return self.service_records.filter(kind=kind).order_by("-performed_at", "-id").first()

    def record_audit(
        self,
        *,
        auditor,
        result: str,
        remarks: str = "",
        audited_at=None,
    ):
        """Validate and append an audit event for this saved resource."""
        from core.labs.models.auditing.resource_audit import ResourceAudit
        from core.labs.models.resource.base.generic_links import resource_content_type

        if self.pk is None:
            raise ValueError("Resource must be saved before it can be audited.")
        if auditor is None or not getattr(auditor, "is_authenticated", False):
            raise ValueError("Auditor must be an authenticated user.")

        audit = ResourceAudit(
            resource_content_type=resource_content_type(self),
            resource_object_id=str(self.pk),
            auditor=auditor,
            result=result,
            remarks=remarks.strip(),
            audited_at=audited_at or timezone.now(),
        )
        audit.full_clean()
        audit.save(actor=auditor)
        return audit

    def __str__(self) -> str:
        return self.name or self.sku or str(self.uid)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=("sku",),
                condition=Q(deleted_at__isnull=True),
                name="%(app_label)s_%(class)s_active_sku_uniq",
            ),
        ]


class ResourceStatusRecordModel(TimeStampedModel, UserStampedModel):
    status = models.CharField(max_length=32)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
        ordering = ("-created", "-id")
