"""Migration to enforce insert-only immutability trigger on TicketActivity in PostgreSQL."""

from django.db import migrations


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            CREATE OR REPLACE FUNCTION prevent_ticket_activity_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'TicketActivity records are immutable and cannot be updated or deleted.';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_update ON support_desk_ticketactivity;
            CREATE TRIGGER trg_prevent_ticket_activity_update
            BEFORE UPDATE ON support_desk_ticketactivity
            FOR EACH ROW EXECUTE FUNCTION prevent_ticket_activity_modification();

            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_delete ON support_desk_ticketactivity;
            CREATE TRIGGER trg_prevent_ticket_activity_delete
            BEFORE DELETE ON support_desk_ticketactivity
            FOR EACH ROW EXECUTE FUNCTION prevent_ticket_activity_modification();
        """)


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_update ON support_desk_ticketactivity;
            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_delete ON support_desk_ticketactivity;
            DROP FUNCTION IF EXISTS prevent_ticket_activity_modification();
        """)


class Migration(migrations.Migration):

    dependencies = [
        ("support_desk", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_trigger, drop_trigger),
    ]
