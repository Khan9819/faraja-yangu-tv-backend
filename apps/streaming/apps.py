from django.apps import AppConfig


class StreamingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.streaming'
    
    def ready(self):
        import apps.streaming.signals
