# Adds thumbnail_url to analytics_notification.
#
# DEPLOY-SAFE: the production DB already has this column (added earlier via
# run_migration.py manual ALTER TABLE). A plain AddField would fail with
# "column already exists", so the database operation only adds the column
# when it is missing. The state operation keeps the model/migrations in sync.
#
# NOTE: the reverse drops the column even when it pre-existed on production
# (standard AddField reverse behavior) — reverse this migration only on a
# disposable/development database.

from django.conf import settings
from django.db import migrations, models


def _column_exists(connection, table, column):
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, table)
    return any(col.name == column for col in columns)


def _build_field():
    field = models.URLField(blank=True, max_length=500)
    field.set_attributes_from_name('thumbnail_url')
    return field


def add_thumbnail_url_if_missing(apps, schema_editor):
    if _column_exists(schema_editor.connection, 'analytics_notification', 'thumbnail_url'):
        return
    Notification = apps.get_model('analytics', 'Notification')
    schema_editor.add_field(Notification, _build_field())


def remove_thumbnail_url(apps, schema_editor):
    if not _column_exists(schema_editor.connection, 'analytics_notification', 'thumbnail_url'):
        return
    Notification = apps.get_model('analytics', 'Notification')
    schema_editor.remove_field(Notification, _build_field())


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0006_alter_notification_options_alter_notification_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_thumbnail_url_if_missing, remove_thumbnail_url),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='notification',
                    name='thumbnail_url',
                    field=models.URLField(blank=True, max_length=500),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', 'is_read'], name='analytics_n_user_id_0f8742_idx'),
        ),
    ]
