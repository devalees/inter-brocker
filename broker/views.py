from django.shortcuts import render
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Webhook
from .serializers import WebhookSerializer
import time
import logging

logger = logging.getLogger(__name__)

# TradingView webhook IPs (disabled for testing)
# TRADINGVIEW_IPS = {
#     '52.89.214.238',
#     '34.212.75.30',
#     '54.218.53.128',
#     '52.32.178.7',
#     '127.0.0.1',
#     'localhost',
#     '172.31.31.33',  # Your EC2 instance private IP
#     '16.170.148.120'  # Your EC2 instance public IP
# }

# Create your views here.

def home(request):
    return HttpResponse("Welcome to Inter-Broker Communication System!")

class WebhookView(APIView):
    def post(self, request, *args, **kwargs):
        start_time = time.time()
        
        # Get the client's IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        # IP check disabled for testing
        # if ip not in TRADINGVIEW_IPS:
        #     return Response(
        #         {"error": "Unauthorized IP address", "received_ip": ip},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        # Log the content type and body for debugging
        logger.warning(f"Webhook received from {ip} with Content-Type: {request.content_type}")
        logger.warning(f"Raw body: {request.body}")

        try:
            if request.content_type == 'text/plain':
                text_content = request.body.decode('utf-8')
                json_payload = {"text": text_content}
            elif request.content_type == 'application/json':
                json_payload = request.data
            else:
                # Accept any content type for debugging
                text_content = request.body.decode('utf-8')
                json_payload = {"raw": text_content, "content_type": request.content_type}
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        # Create webhook data
        webhook_data = {
            'payload': json_payload,
            'headers': dict(request.headers),
            'source_ip': ip
        }

        serializer = WebhookSerializer(data=webhook_data)
        if serializer.is_valid():
            serializer.save()
            
            # Check if we're approaching the 3-second timeout
            if time.time() - start_time > 2.5:  # Leave 0.5s buffer
                return Response(
                    {"warning": "Request processing time approaching limit"},
                    status=status.HTTP_201_CREATED
                )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
