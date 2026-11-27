"""Admin: separate Expiring Banners and One-time Alerts backed by Notification."""

import logging
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import AdminSplitDateTime, BaseAdminDateWidget, BaseAdminTimeWidget
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.websocket.models import AlertNotification, BannerNotification, Notification
from core.websocket.publish_service import publish_notification_record, publish_notification_removed

logger = logging.getLogger(__name__)

DEFAULT_ALERT_RETENTION = timedelta(days=7)


class _DateTimePickerWidget(AdminSplitDateTime):
    """Inline Date + Time picker with one-click presets and live expiry preview."""

    template_name = "websocket/admin/expiry_datetime_widget.html"

    class Media:
        css = {"all": ("websocket/admin_datetime_picker.css",)}
        js = ("websocket/admin_datetime_picker.js",)

    def __init__(self, attrs=None, *, allow_clear: bool = False):
        self.allow_clear = allow_clear
        widgets = [
            BaseAdminDateWidget(attrs={"type": "date"}, format="%Y-%m-%d"),
            BaseAdminTimeWidget(attrs={"type": "time"}, format="%H:%M"),
        ]
        forms.MultiWidget.__init__(self, widgets, attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["timezone_name"] = timezone.get_current_timezone_name()
        context["widget"]["allow_clear"] = self.allow_clear
        return context


class _BannerNotificationForm(forms.ModelForm):
    expiry_date = forms.SplitDateTimeField(
        widget=_DateTimePickerWidget(allow_clear=False),
        help_text=_("Banner stays pinned at the top of Lab Mango until this time."),
    )

    class Meta:
        model = BannerNotification
        fields = ("message", "details", "message_type", "expiry_date", "is_dismissible", "target_user")
        labels = {
            "message_type": _("Banner tone"),
            "is_dismissible": _("Allow users to dismiss"),
        }
        help_texts = {
            "is_dismissible": _(
                "Uncheck to force the banner to stay sticky until expiry (for critical outages or mandatory notices)."
            ),
            "target_user": _("Leave blank to show the banner to all users."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(Notification.TONE_CHOICES)
        if self.instance and self.instance.pk and self.instance.message_type == Notification.ANNOUNCEMENT:
            choices.append((Notification.ANNOUNCEMENT, _("Announcement (legacy)")))
        field = self.fields["message_type"]
        if isinstance(field, forms.ChoiceField):
            field.choices = choices


class _AlertNotificationForm(forms.ModelForm):
    expiry_date = forms.SplitDateTimeField(
        required=False,
        widget=_DateTimePickerWidget(allow_clear=True),
        label=_("Keep in bell history until"),
        help_text=_(
            "Optional. Controls how long the alert stays in the notification bell history (defaults to 7 days). "
            "The popup alert is delivered once on creation."
        ),
    )

    class Meta:
        model = AlertNotification
        fields = ("message", "details", "message_type", "target_user", "expiry_date")
        labels = {
            "message_type": _("Alert tone"),
        }
        help_texts = {
            "target_user": _("Leave blank to send the one-time alert to all online users."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["message_type"]
        if isinstance(field, forms.ChoiceField):
            field.choices = list(Notification.TONE_CHOICES)

    def clean_expiry_date(self):
        value = self.cleaned_data.get("expiry_date")
        if value is None:
            return timezone.now() + DEFAULT_ALERT_RETENTION
        if self.instance._state.adding and value <= timezone.now():
            raise ValidationError(_("Expiry date must be in the future."))
        return value


@admin.action(description=_("Expire selected banners now"))
def expire_banners_now(modeladmin, request, queryset) -> None:
    """Immediately expire selected banners and remove them from open browsers."""
    now = timezone.now()
    targets = list(queryset.filter(expiry_date__gt=now).values_list("pk", "target_user_id"))
    if not targets:
        modeladmin.message_user(request, _("Selected banners are already expired."), level=messages.INFO)
        return

    queryset.filter(pk__in=[pk for pk, _ in targets]).update(expiry_date=now)

    def _notify_removed() -> None:
        for pk, target_user_id in targets:
            publish_notification_removed(pk, display_mode=Notification.BANNER, target_user_id=target_user_id)

    transaction.on_commit(_notify_removed)
    modeladmin.message_user(
        request,
        _("Expired %(count)d banner(s) and removed them from active sessions.") % {"count": len(targets)},
        level=messages.SUCCESS,
    )


@admin.register(BannerNotification)
class BannerNotificationAdmin(admin.ModelAdmin):
    form = _BannerNotificationForm
    list_display = (
        "message",
        "message_type",
        "banner_status",
        "expiry_date",
        "is_dismissible",
        "target_user",
        "created",
    )
    list_filter = ("message_type", "is_dismissible")
    search_fields = ("message", "details", "target_user__username", "target_user__email")
    autocomplete_fields = ("target_user",)
    actions = [expire_banners_now]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(display_mode=Notification.BANNER)

    @admin.display(description=_("Status"))
    def banner_status(self, obj: Notification) -> str:
        return "Active" if obj.expiry_date and obj.expiry_date > timezone.now() else "Expired"

    def save_model(self, request, obj: Notification, form, change: bool) -> None:
        """Save banner and push live upsert/removal after commit (never triggers a toast popup)."""
        obj.display_mode = Notification.BANNER
        now = timezone.now()
        is_active = bool(obj.expiry_date and obj.expiry_date > now)
        if is_active and obj.published_at is None:
            obj.published_at = now
        super().save_model(request, obj, form, change)

        notification_id = obj.pk
        target_user_id = obj.target_user_id
        if is_active:
            event = "updated" if change else "created"
            transaction.on_commit(lambda: publish_notification_record(obj, event=event))
        else:
            transaction.on_commit(
                lambda: publish_notification_removed(
                    notification_id,
                    display_mode=Notification.BANNER,
                    target_user_id=target_user_id,
                )
            )

    def delete_model(self, request, obj: Notification) -> None:
        notification_id = obj.pk
        target_user_id = obj.target_user_id
        super().delete_model(request, obj)
        transaction.on_commit(
            lambda: publish_notification_removed(
                notification_id,
                display_mode=Notification.BANNER,
                target_user_id=target_user_id,
            )
        )

    def delete_queryset(self, request, queryset) -> None:
        targets = list(queryset.values_list("pk", "target_user_id"))
        super().delete_queryset(request, queryset)

        def _notify_removed() -> None:
            for pk, target_user_id in targets:
                publish_notification_removed(pk, display_mode=Notification.BANNER, target_user_id=target_user_id)

        transaction.on_commit(_notify_removed)


@admin.register(AlertNotification)
class AlertNotificationAdmin(admin.ModelAdmin):
    form = _AlertNotificationForm
    list_display = (
        "message",
        "message_type",
        "delivery_status",
        "target_user",
        "published_at",
        "expiry_date",
        "created",
    )
    list_filter = ("message_type",)
    search_fields = ("message", "details", "target_user__username", "target_user__email")
    autocomplete_fields = ("target_user",)
    readonly_fields = ("published_at",)
    actions = []

    def get_queryset(self, request):
        return super().get_queryset(request).filter(display_mode=Notification.ALERT)

    @admin.display(description=_("Delivery"))
    def delivery_status(self, obj: Notification) -> str:
        return "Sent once" if obj.published_at else "Not broadcast"

    def save_model(self, request, obj: Notification, form, change: bool) -> None:
        """Broadcast one-time alerts strictly once on initial creation; edits never re-spam."""
        obj.display_mode = Notification.ALERT
        obj.is_dismissible = True
        now = timezone.now()
        if not obj.expiry_date:
            obj.expiry_date = now + DEFAULT_ALERT_RETENTION

        should_publish = not change and obj.published_at is None and obj.expiry_date > now
        if should_publish:
            obj.published_at = now
        super().save_model(request, obj, form, change)

        if should_publish:
            transaction.on_commit(lambda: publish_notification_record(obj, event="created"))
        elif change:
            self.message_user(
                request,
                _("Alert updated in bell history without re-sending a popup."),
                level=messages.INFO,
            )
