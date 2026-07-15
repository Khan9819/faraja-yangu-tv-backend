# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('advertising', '0005_add_ad_unit_id_and_ad_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='ad',
            name='redirect_link',
            field=models.URLField(blank=True, help_text='URL to redirect when ad is clicked', max_length=500, null=True),
        ),
    ]
