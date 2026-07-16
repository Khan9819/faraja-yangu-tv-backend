from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0023_add_categories_to_videoadslot'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='upload_token',
            field=models.CharField(blank=True, help_text='Long-lived upload session token', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='video',
            name='upload_token_expiry',
            field=models.DateTimeField(blank=True, help_text='Expiry of upload token', null=True),
        ),
    ]
