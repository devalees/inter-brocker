from django.shortcuts import render
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Webhook
from .serializers import WebhookSerializer

# Create your views here.

def home(request):
    return HttpResponse("Welcome to Inter-Broker Communication System!")

class WebhookView(APIView):
    def post(self, request, *args, **kwargs):
        # Get the client's IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        # Create webhook data
        webhook_data = {
            'payload': request.data,
            'headers': dict(request.headers),
            'source_ip': ip
        }

        serializer = WebhookSerializer(data=webhook_data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
