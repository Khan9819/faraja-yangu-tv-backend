import os
import django
from django.core.asgi import get_asgi_application
import logging
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings.base')
django.setup()

# Import routing after Django is set up to avoid app registry errors
from farajayangu_be.ws_urls import ws_urlpatterns

logger = logging.getLogger(__name__)

async def lifespan_handler(scope, receive, send):
    """Handle ASGI lifespan events"""
    message = await receive()
    
    if message['type'] == 'lifespan.startup':
        # Startup logic
        logger.info("Salamba backend starting up...")
        # Add any startup initialization here
        await send({'type': 'lifespan.startup.complete'})
        
    elif message['type'] == 'lifespan.shutdown':
        # Shutdown logic
        logger.info("Salamba backend shutting down...")
        # Add any cleanup logic here
        await send({'type': 'lifespan.shutdown.complete'})

class LifespanProtocolTypeRouter(ProtocolTypeRouter):
    """Extended ProtocolTypeRouter with lifespan support"""
    
    def __init__(self, application_mapping):
        # Add lifespan handler to the mapping
        application_mapping['lifespan'] = lifespan_handler
        super().__init__(application_mapping)


application = LifespanProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(URLRouter(ws_urlpatterns))
})