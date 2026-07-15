from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import close_old_connections
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from apps.authentication.models import User
from apps.streaming.socket.utils import get_video_progress
import json
import logging

logger = logging.getLogger(__name__)


class VideoProcessorConsumer(AsyncWebsocketConsumer):
    group_prefix = "video_progress"

    async def connect(self):
        await database_sync_to_async(close_old_connections)()
        
        # Authenticate user from query string token
        user = await self.authenticate()
        if not user:
            await self.close(code=4001)
            return
        
        self.user = user
        self.video_id = self.scope['url_route']['kwargs']['video_uid']
        self.room_group_name = f"{self.group_prefix}_{self.video_id}"
        
        try:
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            await self.send(json.dumps({
                "type": "connection",
                "status": "connected",
                "message": "Connected to video progress stream",
                "video_id": self.video_id
            }))
            
            # Send current progress state for late-joining clients
            await self.send_current_progress()
            
            logger.info(f"VideoProcessorConsumer connected: {self.channel_name} for video: {self.video_id}, user: {self.user.username}")
        except Exception as e:
            logger.error(f"Error in VideoProcessorConsumer connect: {str(e)}")
            await database_sync_to_async(close_old_connections)()
            raise

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await database_sync_to_async(close_old_connections)()
        logger.info(f"VideoProcessorConsumer disconnected: {self.channel_name}")

    async def authenticate(self):
        """Authenticate user from JWT token in query string."""
        try:
            query_string = self.scope.get('query_string', b'').decode('utf-8')
            params = dict(param.split('=') for param in query_string.split('&') if '=' in param)
            token = params.get('token')
            
            if not token:
                logger.warning("WebSocket connection rejected: No token provided")
                return None
            
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            user = await database_sync_to_async(User.objects.get)(id=user_id)
            return user
        except TokenError as e:
            logger.warning(f"WebSocket connection rejected: Invalid token - {str(e)}")
            return None
        except User.DoesNotExist:
            logger.warning("WebSocket connection rejected: User not found")
            return None
        except Exception as e:
            logger.error(f"WebSocket authentication error: {str(e)}")
            return None

    async def video_progress(self, event):
        """Handle video progress updates from channel layer."""
        await self.send(text_data=json.dumps({
            "type": "progress",
            "stage": event.get("stage"),
            "progress": event.get("progress"),
            "message": event.get("message"),
            "video_id": event.get("video_id"),
            "status": event.get("status", "processing")
        }))

    async def video_complete(self, event):
        """Handle video processing completion."""
        await self.send(text_data=json.dumps({
            "type": "complete",
            "status": "completed",
            "message": event.get("message", "Video processing completed"),
            "video_id": event.get("video_id"),
            "hls_path": event.get("hls_path")
        }))

    async def video_error(self, event):
        """Handle video processing errors."""
        await self.send(text_data=json.dumps({
            "type": "error",
            "status": "failed",
            "message": event.get("message", "Video processing failed"),
            "video_id": event.get("video_id"),
            "error": event.get("error")
        }))

    async def upload_progress(self, event):
        """Handle upload progress updates."""
        await self.send(text_data=json.dumps({
            "type": "upload_progress",
            "video_id": event.get("video_id"),
            "upload_progress": event.get("upload_progress"),
            "completed_chunks": event.get("completed_chunks"),
            "total_chunks": event.get("total_chunks"),
            "message": event.get("message"),
            "is_complete": event.get("is_complete", False)
        }))

    async def send_current_progress(self):
        """
        Send current progress state from database for late-joining clients.
        This allows clients connecting mid-task to immediately see current status.
        """
        try:
            # Get current progress from database
            progress = await database_sync_to_async(get_video_progress)(int(self.video_id))
            
            if not progress:
                return
            
            status = progress.get('status', 'pending')
            
            # Send appropriate message based on current status
            if status == 'completed':
                await self.send(text_data=json.dumps({
                    "type": "complete",
                    "status": "completed",
                    "message": progress.get('message', 'Video processing completed'),
                    "video_id": progress.get('video_id'),
                    "hls_path": progress.get('hls_path')
                }))
            elif status == 'failed':
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "status": "failed",
                    "message": progress.get('message', 'Video processing failed'),
                    "video_id": progress.get('video_id'),
                    "error": None
                }))
            elif status in ('processing', 'assembling'):
                await self.send(text_data=json.dumps({
                    "type": "progress",
                    "stage": progress.get('stage', 'idle'),
                    "progress": progress.get('progress', 0),
                    "message": progress.get('message', ''),
                    "video_id": progress.get('video_id'),
                    "status": status
                }))
            # For 'pending' status, no progress message needed
            
            logger.debug(f"Sent current progress to late-joining client for video {self.video_id}")
        except Exception as e:
            logger.warning(f"Could not send current progress for video {self.video_id}: {str(e)}")