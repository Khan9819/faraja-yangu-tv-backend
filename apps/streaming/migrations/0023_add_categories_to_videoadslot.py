from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streaming', '0022_add_tv_image_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='videoadslot',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='ad_slots', to='streaming.category'),
        ),
    ]
