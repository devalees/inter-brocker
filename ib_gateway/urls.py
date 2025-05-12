from django.urls import path
from . import views

app_name = 'ib_gateway'

urlpatterns = [
    path('status/', views.connection_status, name='connection_status'),
    path('orders/', views.OrderView.as_view(), name='orders'),
    path('orders/<str:order_id>/', views.OrderView.as_view(), name='order_detail'),
] 