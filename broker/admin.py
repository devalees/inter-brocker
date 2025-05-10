from django.contrib import admin
from .models import Webhook

@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'source_ip')
    list_filter = ('received_at', 'source_ip')
    readonly_fields = ('received_at', 'source_ip', 'payload', 'headers')
    search_fields = ('source_ip',)
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation of webhooks
