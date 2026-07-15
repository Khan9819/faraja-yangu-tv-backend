import os
from django.core.management.base import BaseCommand
from django.core.management import execute_from_command_line


class Command(BaseCommand):
    help = 'Create a new app with NTC structure'

    def add_arguments(self, parser):
        parser.add_argument('app_name', type=str, help='Name of the app to create')

    def handle(self, *args, **options):
        app_name = options['app_name']
        
        # Sanitize app name (remove domain extensions, replace dots with underscores)
        app_name = self.sanitize_name(app_name)
        
        self.stdout.write(f'Creating app: {app_name}')
        
        # Create the app directory structure
        self.create_app_structure(app_name)
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created app "{app_name}"')
        )

    def sanitize_name(self, name):
        """Sanitize project/app name by removing TLD and replacing dots with underscores."""
        # Common TLDs to remove
        tlds = ['.com', '.org', '.net', '.io', '.co', '.app', '.dev', '.tech', '.ai']
        
        # Remove TLD if present
        for tld in tlds:
            if name.lower().endswith(tld):
                name = name[:-len(tld)]
                break
        
        # Replace dots with underscores
        name = name.replace('.', '_')
        
        # Remove any other invalid characters and ensure it starts with a letter
        import re
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        if name and name[0].isdigit():
            name = 'app_' + name
            
        return name.lower()

    def create_app_structure(self, app_name):
        """Create the app directory structure."""
        base_path = os.path.join('apps', app_name)
        
        # Create directories
        directories = [
            base_path,
            os.path.join(base_path, 'permissions'),
            os.path.join(base_path, 'serializers'),
            os.path.join(base_path, 'selectors'),
            os.path.join(base_path, 'services'),
            os.path.join(base_path, 'socket'),
            os.path.join(base_path, 'tasks'),
            os.path.join(base_path, 'tests'),
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            # Create __init__.py in each directory
            init_file = os.path.join(directory, '__init__.py')
            if not os.path.exists(init_file):
                with open(init_file, 'w') as f:
                    f.write('')
        
        # Create main app files
        files_content = {
            'admin.py': f'''from django.contrib import admin

# Register your models here.
''',
            'apps.py': f'''from django.apps import AppConfig


class {app_name.title()}Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.{app_name}'
''',
            'models.py': f'''from django.db import models
from apps.common.models import TimeStampedModel

# Create your models here.
''',
            'urls.py': f'''from django.urls import path
from . import views

app_name = '{app_name}'

urlpatterns = [
    # Add your URL patterns here
]
''',
            'views.py': f'''from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response

# Create your views here.
''',
        }
        
        for filename, content in files_content.items():
            file_path = os.path.join(base_path, filename)
            with open(file_path, 'w') as f:
                f.write(content)
        
        self.stdout.write(f'Created app structure in apps/{app_name}/')
