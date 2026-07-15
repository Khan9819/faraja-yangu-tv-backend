from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0018_unique_view_per_user_per_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='conversion_job_id',
            field=models.UUIDField(null=True, blank=True, db_index=True, help_text='UUID of the conversion job in the C++ microservice'),
        ),
        migrations.AddField(
            model_name='video',
            name='processing_backend',
            field=models.CharField(max_length=32, default='python', choices=[('python', 'Python'), ('cpp', 'C++')], help_text='Which backend processed/is processing this video'),
        ),
        migrations.AddField(
            model_name='video',
            name='queued_at',
            field=models.DateTimeField(null=True, blank=True, help_text='When the conversion job was queued'),
        ),
        migrations.AddField(
            model_name='video',
            name='processing_started_at',
            field=models.DateTimeField(null=True, blank=True, help_text='When conversion actually started'),
        ),
        migrations.AddField(
            model_name='video',
            name='processing_completed_at',
            field=models.DateTimeField(null=True, blank=True, help_text='When conversion completed'),
        ),
        migrations.AddField(
            model_name='video',
            name='processing_failed_at',
            field=models.DateTimeField(null=True, blank=True, help_text='When conversion last failed'),
        ),
        migrations.AddField(
            model_name='video',
            name='last_processing_heartbeat_at',
            field=models.DateTimeField(null=True, blank=True, help_text='Last heartbeat from conversion worker'),
        ),
        migrations.AddField(
            model_name='video',
            name='last_event_received_at',
            field=models.DateTimeField(null=True, blank=True, help_text='Last event received from conversion worker'),
        ),
        migrations.AddField(
            model_name='video',
            name='retry_count',
            field=models.PositiveIntegerField(default=0, help_text='Number of conversion retry attempts'),
        ),
    ]
