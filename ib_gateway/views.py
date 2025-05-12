from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import IBConfig, Order
from .connection import IBConnection, test_connection
import json
import logging
import decimal
import time
import datetime

logger = logging.getLogger(__name__)

def connection_status(request):
    """View to check IB Gateway connection status"""
    try:
        # Get the active configuration
        config = IBConfig.objects.filter(is_active=True).first()
        if not config:
            return JsonResponse({
                'success': False,
                'message': 'No active IB Gateway configuration found'
            })
            
        # Test the connection
        success, message = test_connection(
            host=config.host,
            port=config.port,
            client_id=config.client_id
        )
        
        return JsonResponse({
            'success': success,
            'message': message,
            'config': {
                'host': config.host,
                'port': config.port,
                'client_id': config.client_id
            }
        })
    except Exception as e:
        logger.error(f"Error checking IB Gateway connection: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f"Error: {str(e)}"
        }, status=500)


# Map IB order statuses to our database statuses
IB_STATUS_MAPPING = {
    'PendingSubmit': 'PENDING',
    'PendingCancel': 'PENDING',
    'PreSubmitted': 'SUBMITTED',
    'Submitted': 'SUBMITTED',
    'ApiPending': 'SUBMITTED',
    'ApiCancelled': 'CANCELLED',
    'Cancelled': 'CANCELLED',
    'Filled': 'FILLED',
    'Inactive': 'REJECTED',
}

def map_ib_status(ib_status):
    """Map IB status to our database status"""
    return IB_STATUS_MAPPING.get(ib_status, 'PENDING')


class OrderView(APIView):
    """View to create and manage orders"""
    
    @csrf_exempt
    def post(self, request, *args, **kwargs):
        """Create a new order"""
        try:
            # Get request data
            data = request.data
            
            # Validate required fields
            required_fields = ['symbol', 'action', 'quantity']
            for field in required_fields:
                if field not in data:
                    return Response({
                        'success': False,
                        'message': f"Missing required field: {field}"
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
            # Get optional fields with defaults
            order_type = data.get('order_type', 'MKT')
            limit_price = data.get('limit_price', None)
            stop_price = data.get('stop_price', None)
            
            # Get the active configuration
            config = IBConfig.objects.filter(is_active=True).first()
            if not config:
                return Response({
                    'success': False,
                    'message': 'No active IB Gateway configuration found'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # Connect to IB Gateway
            ib = IBConnection(config.host, config.port, config.client_id)
            if not ib.connect():
                return Response({
                    'success': False,
                    'message': 'Failed to connect to IB Gateway'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
            # Create contract
            contract = ib.create_contract(
                symbol=data['symbol'],
                sec_type=data.get('sec_type', 'STK'),
                exchange=data.get('exchange', 'SMART'),
                currency=data.get('currency', 'USD')
            )
            
            # Create order
            order_args = {
                'action': data['action'],
                'quantity': decimal.Decimal(data['quantity']),
                'order_type': order_type
            }
            
            if limit_price and order_type in ('LMT', 'STP_LMT'):
                order_args['limit_price'] = decimal.Decimal(limit_price)
                
            if stop_price and order_type in ('STP', 'STP_LMT'):
                order_args['stop_price'] = decimal.Decimal(stop_price)
                
            order_obj = ib.create_order(**order_args)
            
            if not order_obj:
                ib.disconnect()
                return Response({
                    'success': False,
                    'message': 'Failed to create order'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
            # Use a unique order ID based on timestamp if needed
            if data.get('use_timestamp_id', False):
                # Generate a shorter timestamp-based ID 
                # Use the last 6 digits of the current timestamp
                # This avoids the error with large numbers
                timestamp = int(time.time()) % 1000000
                ib.api.next_order_id = timestamp + 1
                
            # Place the order
            order_id = ib.place_order(contract, order_obj)
            
            if not order_id:
                ib.disconnect()
                return Response({
                    'success': False,
                    'message': 'Failed to place order'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
            # Save order in database
            webhook_id = data.get('webhook_id', None)
            webhook = None
            if webhook_id:
                from broker.models import Webhook
                try:
                    webhook = Webhook.objects.get(id=webhook_id)
                except Webhook.DoesNotExist:
                    pass
                    
            db_order = Order(
                order_id=str(order_id),
                action=data['action'],
                symbol=data['symbol'],
                sec_type=data.get('sec_type', 'STK'),
                exchange=data.get('exchange', 'SMART'),
                currency=data.get('currency', 'USD'),
                quantity=decimal.Decimal(data['quantity']),
                order_type=order_type,
                status='SUBMITTED',
                webhook=webhook
            )
            
            if limit_price and order_type in ('LMT', 'STP_LMT'):
                db_order.limit_price = decimal.Decimal(limit_price)
                
            if stop_price and order_type in ('STP', 'STP_LMT'):
                db_order.stop_price = decimal.Decimal(stop_price)
                
            db_order.save()
            
            # Wait for initial order status update
            logger.info(f"Waiting for order status for order {order_id}")
            order_status = ib.wait_for_order_status(order_id, timeout=5)
            
            if order_status:
                logger.info(f"Received order status: {order_status}")
                # Update the order in the database
                status_name = map_ib_status(order_status['status'])
                db_order.status = status_name
                
                if order_status['filled'] > 0:
                    db_order.filled_quantity = decimal.Decimal(order_status['filled'])
                    
                if order_status['avgFillPrice'] > 0:
                    db_order.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                    
                db_order.save()
            
            # Disconnect from IB Gateway
            ib.disconnect()
            
            return Response({
                'success': True,
                'message': f'Order placed successfully with ID: {order_id}',
                'order_id': order_id,
                'order': {
                    'id': db_order.id,
                    'order_id': db_order.order_id,
                    'action': db_order.action,
                    'symbol': db_order.symbol,
                    'quantity': float(db_order.quantity),
                    'order_type': db_order.order_type,
                    'status': db_order.status,
                    'filled_quantity': float(db_order.filled_quantity) if db_order.filled_quantity else 0,
                    'avg_fill_price': float(db_order.avg_fill_price) if db_order.avg_fill_price else None
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return Response({
                'success': False,
                'message': f"Error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    def get(self, request, order_id=None, *args, **kwargs):
        """Get order information"""
        if order_id:
            # Get a specific order
            try:
                order = Order.objects.get(order_id=order_id)
                
                # If requested, check for real-time updates
                refresh = request.GET.get('refresh', 'false').lower() == 'true'
                
                if refresh:
                    try:
                        # Connect to IB Gateway and check order status
                        config = IBConfig.objects.filter(is_active=True).first()
                        if config:
                            ib = IBConnection(config.host, config.port, config.client_id)
                            if ib.connect():
                                order_status = ib.get_order_status(order_id)
                                if order_status:
                                    # Update the order in the database
                                    status_name = map_ib_status(order_status['status'])
                                    order.status = status_name
                                    
                                    if order_status['filled'] > 0:
                                        order.filled_quantity = decimal.Decimal(order_status['filled'])
                                        
                                    if order_status['avgFillPrice'] > 0:
                                        order.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                                        
                                    order.save()
                                
                                # Get execution details
                                execution_details = ib.get_execution_details(order_id)
                                
                                # Disconnect
                                ib.disconnect()
                    except Exception as e:
                        logger.error(f"Error refreshing order status: {str(e)}")
                
                return Response({
                    'success': True,
                    'order': {
                        'id': order.id,
                        'order_id': order.order_id,
                        'action': order.action,
                        'symbol': order.symbol,
                        'quantity': float(order.quantity),
                        'order_type': order.order_type,
                        'status': order.status,
                        'filled_quantity': float(order.filled_quantity) if order.filled_quantity else 0,
                        'avg_fill_price': float(order.avg_fill_price) if order.avg_fill_price else None,
                        'created_at': order.created_at
                    }
                })
            except Order.DoesNotExist:
                return Response({
                    'success': False,
                    'message': f"Order with ID {order_id} not found"
                }, status=status.HTTP_404_NOT_FOUND)
        else:
            # List all orders, with pagination
            page = int(request.GET.get('page', 1))
            limit = int(request.GET.get('limit', 10))
            
            start = (page - 1) * limit
            end = page * limit
            
            orders = Order.objects.all().order_by('-created_at')[start:end]
            total = Order.objects.count()
            
            return Response({
                'success': True,
                'orders': [{
                    'id': order.id,
                    'order_id': order.order_id,
                    'action': order.action,
                    'symbol': order.symbol,
                    'quantity': float(order.quantity),
                    'order_type': order.order_type,
                    'status': order.status,
                    'filled_quantity': float(order.filled_quantity) if order.filled_quantity else 0,
                    'created_at': order.created_at
                } for order in orders],
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            }) 