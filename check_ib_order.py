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

def check_order(order_id="63415"):
    """Check a specific order by ID"""
    
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
        # Try to get the order from the database
        try:
            db_order = Order.objects.get(order_id=order_id)
            logger.info(f"Found order in database: {db_order.order_id} - {db_order.symbol} {db_order.action} {db_order.quantity}")
            logger.info(f"Order status in DB: {db_order.status}")
        except Order.DoesNotExist:
            logger.error(f"Order {order_id} not found in database")
            db_order = None
            
        # Get order status from IB
        logger.info(f"Requesting status for order {order_id} from IB Gateway...")
        status = ib.get_order_status(order_id)
        
        if status:
            logger.info(f"IB Order Status: {status}")
        else:
            logger.info(f"Order {order_id} not found in IB Gateway or no status available")
            
        # Try to check any error messages for this order
        logger.info("Checking recent error messages in IB Gateway connection...")
        
        # Reconnect with a new client ID to avoid conflicts
        logger.info("Reconnecting with a new client ID...")
        ib.disconnect()
        time.sleep(1)
        
        # Connect with a different client ID to get fresh data
        ib = IBConnection(config.host, config.port, config.client_id + 1)
        if not ib.connect():
            logger.error("Failed to reconnect to IB Gateway")
            return
            
        # Try to place the order again (with auto_id=False to use the same order ID)
        # This might trigger the same error message
        if db_order:
            logger.info(f"Creating test contract for {db_order.symbol}...")
            contract = ib.create_contract(
                symbol=db_order.symbol,
                sec_type=db_order.sec_type,
                exchange=db_order.exchange,
                currency=db_order.currency
            )
            
            logger.info(f"Creating test order {db_order.action} {db_order.quantity}...")
            test_order = ib.create_order(
                action=db_order.action,
                quantity=float(db_order.quantity),
                order_type=db_order.order_type
            )
            
            if test_order:
                # Set the order ID manually to match the original order
                logger.info(f"Setting order ID to {order_id} and checking for errors...")
                try:
                    # Force the next_order_id to be our specific order_id
                    original_next_id = ib.api.next_order_id
                    ib.api.next_order_id = int(order_id)
                    
                    # Place the order - this might reproduce the error
                    ib.place_order(contract, test_order)
                    
                    # Wait a moment for any errors
                    time.sleep(2)
                    
                    # Restore the original next_order_id
                    ib.api.next_order_id = original_next_id
                    
                except Exception as e:
                    logger.error(f"Error during test order: {str(e)}")
            else:
                logger.error("Failed to create test order")
                
    except Exception as e:
        logger.error(f"Error checking order: {str(e)}")
    finally:
        # Always disconnect
        logger.info("Disconnecting from IB Gateway")
        ib.disconnect()

if __name__ == "__main__":
    # Get order ID from command line or use default
    order_id = sys.argv[1] if len(sys.argv) > 1 else "63415"
    check_order(order_id) 