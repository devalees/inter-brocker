from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/webhook/', views.WebhookView.as_view(), name='webhook'),
] 