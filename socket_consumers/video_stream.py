from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import close_old_connections
import json
import logging

logger = logging.getLogger(__name__)


class VideoStreamConsumer(AsyncWebsocketConsumer):
    chat_group = "stream_broadcast"

    async def connect(self):
        # Close any existing database connections before starting a new WebSocket connection
        await database_sync_to_async(close_old_connections)()
        
        self.video_id = self.scope['url_route']['kwargs']['video_id']
        self.room_group_name = f"chat_{self.chat_group}_{self.video_id}"
        
        try:
            # Add the consumer to the group to receive broadcast messages
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)

            # Accept the WebSocket connection
            await self.accept()

            # Send a greeting message when the client connects
            await self.send(json.dumps({
                "success": True,
                "status": "listening",
                "message": "Connected To Server"
            }))
            
            logger.info(f"VideoStreamConsumer connection established: {self.channel_name} for video: {self.video_id}")
        except Exception as e:
            logger.error(f"Error in VideoStreamConsumer connect: {str(e)}")
            # Make sure to close connections on error
            await database_sync_to_async(close_old_connections)()
            raise

    async def disconnect(self, close_code):
        # Called when the socket closes
        # Remove the consumer from the group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Receive a message from the client

        # Use try-except to handle any exceptions gracefully
        try:
            message = json.loads(text_data)  # Parse the received JSON message
        except json.JSONDecodeError:
            await self.send("Invalid JSON format")
            return
        
    async def video_stream(self, event):
        # Receive a broadcast message from the group
        message = json.dumps(event["message"])
        # Send the message to the WebSocket
        await self.send(text_data=message)