import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings.base')

def pytest_configure():
    django.setup()
