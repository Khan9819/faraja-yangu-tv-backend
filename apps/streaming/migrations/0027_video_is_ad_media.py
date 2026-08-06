# Generated manually — adds is_ad_media flag to Video.
# True = video record is ad media (interceptor ads), excluded from content lists.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0026_videoadslot_categories'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='is_ad_media',
            field=models.BooleanField(default=False, help_text='True when this video record is media for an ad (interceptor etc). Excluded from content lists.'),
        ),
    ]
