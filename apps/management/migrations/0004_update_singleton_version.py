from django.db import migrations

# Hakikisha singleton ya PlatformSettings ina version sahihi ya update
# (inabidi ibadilike kwa usafiri wa DB uliopo — siyo defaults pekee).
def set_version(apps, schema_editor):
    PlatformSettings = apps.get_model('management', 'PlatformSettings')
    obj = PlatformSettings.objects.first()
    if obj is not None:
        obj.app_version = '1.1.1'
        obj.minimum_version = '1.1.0'
        obj.update_url = 'https://play.google.com/store/apps/details?id=co.tz.farajayangutv.app'
        obj.release_notes = [
            'Matangazo yameboreshwa — AdMob ndiyo primary sasa',
            'Player wa video amerekebishwa (web player + app)',
            'Uboreshaji wa utendaji na maboresho mengine',
        ]
        obj.save(update_fields=['app_version', 'minimum_version', 'update_url', 'release_notes'])


class Migration(migrations.Migration):
    dependencies = [
        ('management', '0003_platformsettings_is_force_update_and_more'),
    ]

    operations = [
        migrations.RunPython(set_version, migrations.RunPython.noop),
    ]
