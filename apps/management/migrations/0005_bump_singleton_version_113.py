from django.db import migrations

# Bump ya latest_version kwenda 1.1.3 ili watumiaji wa versions za zamani
# (zikiwemo builds zenye hardcoded '1.1.1') wapate update card na ku-update
# kwenda release mpya. Inafuata pattern ya 0004_update_singleton_version.
def set_version(apps, schema_editor):
    PlatformSettings = apps.get_model('management', 'PlatformSettings')
    obj = PlatformSettings.objects.first()
    if obj is not None:
        obj.app_version = '1.1.3'
        obj.minimum_version = '1.1.0'
        obj.release_notes = [
            'Tangazo la interceptor linasasa cheza mwanzo kabla ya video (pre-roll)',
            'Kadi ya update imeboreshwa — utaambiwa haraka version mpya ikipatikana',
            'Uboreshaji wa utendaji na marekebisho madogo madogo',
        ]
        obj.save(update_fields=['app_version', 'minimum_version', 'release_notes'])


class Migration(migrations.Migration):
    dependencies = [
        ('management', '0004_update_singleton_version'),
    ]

    operations = [
        migrations.RunPython(set_version, migrations.RunPython.noop),
    ]
