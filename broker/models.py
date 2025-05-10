from django.db import models

# Create your models here.

class Webhook(models.Model):
    payload = models.JSONField()
    headers = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    
    def __str__(self):
        return f"Webhook received at {self.received_at}"
