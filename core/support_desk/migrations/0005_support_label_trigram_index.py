"""Migration adding concurrent pg_trgm search index on SupportLabel (ADR 002, section 20.4)."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("support_desk", "0004_backfill_helpdesk_defaults"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="supportlabel",
            index=GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="support_label_name_trgm_idx"),
        ),
    ]
