# Adds the portrait_cover field to Video.
# This was previously part of a regenerated 0025; it is isolated here because
# the production server already applied a differently-named 0025.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0027_video_is_ad_media'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='portrait_cover',
            field=models.ImageField(blank=True, help_text='Portrait cover image for mobile app (1080x1350 recommended)', max_length=500, null=True, upload_to='videos/portrait'),
        ),
    ]
