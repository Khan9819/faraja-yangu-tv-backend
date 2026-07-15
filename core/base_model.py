from django.db import models
from uuid import uuid4
class BaseModel(models.Model):
    id = models.BigAutoField(primary_key=True)
    uid = models.UUIDField(unique=True, default=uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
