# Renamed to match the migration already applied on the production server:
# 0025_remove_videoadslot_categories_video_download_path.
# Do NOT re-generate this file — the server's django_migrations table records
# this exact name, so it is skipped on deploy. portrait_cover moved to 0028.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0024_add_upload_token_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='videoadslot',
            name='categories',
        ),
        migrations.AddField(
            model_name='video',
            name='download_path',
            field=models.CharField(blank=True, help_text='Path to downloadable MP4 file in R2 storage (videos/downloads/)', max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='video',
            name='notification_sent',
            field=models.BooleanField(default=False, help_text='Whether push notification has been sent for this video'),
        ),
    ]
