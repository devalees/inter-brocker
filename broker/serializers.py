from rest_framework import serializers
from .models import Webhook

class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webhook
        fields = ['id', 'payload', 'headers', 'received_at', 'source_ip']
        read_only_fields = ['received_at'] 