"""Remove the retired Jira integration: drop its tables and bookkeeping rows.

The Jira app no longer exists in the code base (ADR 001, Q4). Its data is deleted. This migration is
irreversible on purpose: rolling it back cannot restore the data, so restore from a backup instead.
"""

from django.db import migrations

APP_LABEL = "jira_integration"
# Child table first: the request table holds the foreign key to the configuration table.
TABLES = ("jira_integration_jiraissuerequest", "jira_integration_jiraconfiguration")


def drop_jira_data(apps, schema_editor):
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    for table in TABLES:
        schema_editor.execute(f"DROP TABLE IF EXISTS {quote(table)}")

    ContentType = apps.get_model("contenttypes", "ContentType")
    # Deleting the content types also removes their permissions through the cascade.
    ContentType.objects.filter(app_label=APP_LABEL).delete()

    schema_editor.execute(
        f"DELETE FROM {quote('django_migrations')} WHERE {quote('app')} = %s",
        [APP_LABEL],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_urs_group_labs_role"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(drop_jira_data, elidable=False)]
