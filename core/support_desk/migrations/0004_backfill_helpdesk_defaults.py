"""Data migration: backfill the new helpdesk columns for rows created before 0003."""

from django.db import migrations
from django.db.models import F
from django.utils.text import slugify


def backfill(apps, schema_editor):
    SupportStatus = apps.get_model("support_desk", "SupportStatus")
    SupportTicket = apps.get_model("support_desk", "SupportTicket")
    SupportCategory = apps.get_model("support_desk", "SupportCategory")
    SupportPriority = apps.get_model("support_desk", "SupportPriority")

    # The previous code identified the terminal status by the literal name "Closed".
    SupportStatus.objects.filter(name__iexact="closed", system_state="done").update(is_final=True)
    # "Waiting"-state statuses are where SLA clocks used to be implicitly meaningless: pause them by default.
    SupportStatus.objects.filter(system_state="waiting").update(pauses_sla=True)

    # Existing tickets: activity clock starts at their last update. SLA targets are NOT applied retroactively.
    SupportTicket.objects.update(last_activity_at=F("updated_at"))

    for model in (SupportCategory, SupportPriority):
        for row in model.objects.filter(code=""):
            row.code = slugify(row.name)[:50]
            row.save(update_fields=["code"])


class Migration(migrations.Migration):

    dependencies = [
        ("support_desk", "0003_helpdesk_professionalization"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
