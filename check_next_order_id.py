#!/usr/bin/env python3
import sys
import os
import time
import logging
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inter_broker.settings')
django.setup()

from ib_gateway.models import IBConfig, Order
from ib_gateway.connection import IBConnection

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_next_order_id():
    """Check the next valid order ID from IB Gateway"""
    
    # Get the active configuration
    config = IBConfig.objects.filter(is_active=True).first()
    if not config:
        logger.error("No active IB Gateway configuration found")
        return
        
    logger.info(f"Connecting to IB Gateway at {config.host}:{config.port}")
    
    # Connect to IB Gateway
    ib = IBConnection(config.host, config.port, config.client_id)
    if not ib.connect():
        logger.error("Failed to connect to IB Gateway")
        return
    
    try:
        # Check the next valid order ID
        logger.info(f"Next valid order ID from IB Gateway: {ib.api.next_order_id}")
        
        # Get all orders from the database
        db_orders = Order.objects.filter(order_id__isnull=False).order_by('-created_at')
        logger.info(f"Found {db_orders.count()} orders with IDs in the database:")
        
        # Show the most recent orders
        for order in db_orders[:10]:
            try:
                order_id_int = int(order.order_id)
                logger.info(f"Order ID: {order.order_id} (int: {order_id_int}) - {order.symbol} {order.action} {order.quantity} - Status: {order.status}")
            except (ValueError, TypeError):
                logger.info(f"Order ID: {order.order_id} (not an integer) - {order.symbol} {order.action} {order.quantity} - Status: {order.status}")
        
        # Check if any order IDs are close to the next valid order ID
        if ib.api.next_order_id:
            high_order_ids = []
            for order in db_orders:
                try:
                    order_id_int = int(order.order_id)
                    if order_id_int > ib.api.next_order_id - 1000 and order_id_int < ib.api.next_order_id:
                        high_order_ids.append((order_id_int, order))
                except (ValueError, TypeError):
                    pass
                    
            if high_order_ids:
                high_order_ids.sort(reverse=True)
                logger.info(f"Found {len(high_order_ids)} order IDs close to the next valid order ID:")
                for order_id_int, order in high_order_ids[:5]:
                    logger.info(f"  Order ID: {order_id_int} - {order.symbol} {order.action} {order.quantity}")
            
            # Suggest an order ID to use
            suggested_id = ib.api.next_order_id
            logger.info(f"Suggested order ID to use: {suggested_id}")
            
    except Exception as e:
        logger.error(f"Error checking next order ID: {str(e)}")
    finally:
        # Always disconnect
        logger.info("Disconnecting from IB Gateway")
        ib.disconnect()

if __name__ == "__main__":
    check_next_order_id() 