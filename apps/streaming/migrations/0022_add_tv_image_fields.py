from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0021_add_comment_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='tv_poster',
            field=models.ImageField(blank=True, help_text='TV poster image (540x720 recommended)', max_length=500, null=True, upload_to='videos/tv'),
        ),
        migrations.AddField(
            model_name='video',
            name='tv_landscape',
            field=models.ImageField(blank=True, help_text='TV landscape/banner image (1280x720 recommended)', max_length=500, null=True, upload_to='videos/tv'),
        ),
        migrations.AddField(
            model_name='video',
            name='tv_square',
            field=models.ImageField(blank=True, help_text='TV square image (540x540 recommended)', max_length=500, null=True, upload_to='videos/tv'),
        ),
    ]
