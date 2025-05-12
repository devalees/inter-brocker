from django.core.management.base import BaseCommand
from ib_gateway.models import IBConfig, Order
from ib_gateway.connection import IBConnection
from ib_gateway.views import map_ib_status
import time
import logging
import decimal

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Update order statuses from IB Gateway'
    
    def add_arguments(self, parser):
        parser.add_argument('--order-id', type=str, help='Specific order ID to update')
        parser.add_argument('--all', action='store_true', help='Update all open orders')
        parser.add_argument('--wait', type=int, default=5, help='Time to wait for updates in seconds')
    
    def handle(self, *args, **options):
        order_id = options.get('order_id')
        update_all = options.get('all')
        wait_time = options.get('wait')
        
        if not (order_id or update_all):
            self.stdout.write(self.style.ERROR("Please specify --order-id or --all"))
            return
            
        # Get the active configuration
        config = IBConfig.objects.filter(is_active=True).first()
        if not config:
            self.stdout.write(self.style.ERROR("No active IB Gateway configuration found"))
            return
            
        # Connect to IB Gateway
        self.stdout.write(self.style.NOTICE(f"Connecting to IB Gateway at {config.host}:{config.port}"))
        ib = IBConnection(config.host, config.port, config.client_id)
        if not ib.connect():
            self.stdout.write(self.style.ERROR("Failed to connect to IB Gateway"))
            return
            
        try:
            if order_id:
                # Update a specific order
                self.update_order(ib, order_id, wait_time)
            elif update_all:
                # Update all open orders
                self.update_all_orders(ib, wait_time)
        finally:
            # Disconnect from IB Gateway
            ib.disconnect()
            self.stdout.write(self.style.SUCCESS("Disconnected from IB Gateway"))
            
    def update_order(self, ib, order_id, wait_time):
        """Update a specific order"""
        try:
            order = Order.objects.get(order_id=order_id)
            self.stdout.write(self.style.NOTICE(f"Updating order {order_id} - {order.action} {order.quantity} {order.symbol}"))
            
            # Check order status
            order_status = ib.get_order_status(order_id)
            if not order_status:
                # Wait for a status update
                self.stdout.write(self.style.NOTICE(f"Waiting for order status updates (up to {wait_time} seconds)"))
                order_status = ib.wait_for_order_status(order_id, timeout=wait_time)
                
            if order_status:
                self.stdout.write(self.style.SUCCESS(f"Received order status: {order_status}"))
                # Update the order in the database
                status_name = map_ib_status(order_status['status'])
                old_status = order.status
                order.status = status_name
                
                if order_status['filled'] > 0:
                    order.filled_quantity = decimal.Decimal(order_status['filled'])
                    
                if order_status['avgFillPrice'] > 0:
                    order.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                    
                order.save()
                
                if old_status != status_name:
                    self.stdout.write(self.style.SUCCESS(f"Order status changed from {old_status} to {status_name}"))
            else:
                self.stdout.write(self.style.WARNING(f"No status updates received for order {order_id}"))
                
        except Order.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Order with ID {order_id} not found"))
            
    def update_all_orders(self, ib, wait_time):
        """Update all open orders"""
        # Get all orders that are not in a final state
        open_statuses = ['PENDING', 'SUBMITTED', 'ACCEPTED']
        open_orders = Order.objects.filter(status__in=open_statuses)
        
        if not open_orders:
            self.stdout.write(self.style.NOTICE("No open orders to update"))
            return
            
        self.stdout.write(self.style.NOTICE(f"Updating {open_orders.count()} open orders"))
        
        # Request real-time updates for orders
        self.stdout.write(self.style.NOTICE(f"Waiting for order status updates (up to {wait_time} seconds)"))
        
        start_time = time.time()
        updated_orders = set()
        
        # Let some updates come in
        while time.time() - start_time < wait_time:
            try:
                # Process updates from the queue
                if ib.api.order_status_updates.empty():
                    time.sleep(0.5)
                    continue
                    
                update = ib.api.order_status_updates.get(block=False)
                order_id = update['orderId']
                
                try:
                    order = Order.objects.get(order_id=order_id)
                    updated_orders.add(order_id)
                    
                    # Update the order in the database
                    status_name = map_ib_status(update['status'])
                    old_status = order.status
                    order.status = status_name
                    
                    if update['filled'] > 0:
                        order.filled_quantity = decimal.Decimal(update['filled'])
                        
                    if update['avgFillPrice'] > 0:
                        order.avg_fill_price = decimal.Decimal(update['avgFillPrice'])
                        
                    order.save()
                    
                    if old_status != status_name:
                        self.stdout.write(self.style.SUCCESS(f"Order {order_id} status changed from {old_status} to {status_name}"))
                        
                except Order.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"Received update for unknown order {order_id}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing update: {str(e)}"))
        
        # Check any orders that didn't get updates
        for order in open_orders:
            if order.order_id not in updated_orders:
                self.stdout.write(self.style.NOTICE(f"No updates received for order {order.order_id}, checking status directly"))
                self.update_order(ib, order.order_id, 1)  # Quick check 