"""Migration operations retained for the device-monitoring replacement history."""

from contextlib import contextmanager
from typing import Iterator

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import ProjectState


@contextmanager
def _schema_lock_timeout(schema_editor: BaseDatabaseSchemaEditor) -> Iterator[None]:
    """Restore the caller's session setting even when concurrent DDL fails."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        previous = cursor.fetchone()[0]
    schema_editor.execute("SET lock_timeout = '5s'")
    try:
        yield
    finally:
        schema_editor.execute("SELECT set_config('lock_timeout', %s, false)", [previous])


class AddIndexConcurrentlyWithTimeout(AddIndexConcurrently):
    """Use Django's concurrent forward/reverse operation with bounded lock waits."""

    def database_forwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        with _schema_lock_timeout(schema_editor):
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        with _schema_lock_timeout(schema_editor):
            super().database_backwards(app_label, schema_editor, from_state, to_state)
