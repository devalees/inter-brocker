#!/usr/bin/env python3
import sys
import os
import time
import logging
import django
import random

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

def place_order_to_ib(symbol="AAPL", action="BUY", quantity=1, order_type="MKT", 
                     sec_type="STK", exchange="SMART", currency="USD"):
    """Place an order directly to IB Gateway and check status"""
    
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
        # Use IB Gateway's next valid order ID instead of generating our own
        if not ib.api.next_order_id:
            logger.error("No valid order ID from IB Gateway")
            return
            
        logger.info(f"Using next order ID from IB Gateway: {ib.api.next_order_id}")
        
        # Create contract
        logger.info(f"Creating contract for {symbol}...")
        contract = ib.create_contract(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            currency=currency
        )
        
        # Create order
        logger.info(f"Creating order {action} {quantity} {order_type}...")
        order = ib.create_order(
            action=action,
            quantity=float(quantity),
            order_type=order_type
        )
        
        if not order:
            logger.error("Failed to create order")
            return
            
        # Place the order
        logger.info(f"Placing order...")
        order_id = ib.place_order(contract, order)
        
        if not order_id:
            logger.error("Failed to place order")
            return
            
        logger.info(f"Order placed successfully. Order ID: {order_id}")
        
        # Wait for order status updates
        logger.info(f"Waiting for order status updates...")
        status = None
        
        # Wait up to 10 seconds for status updates
        for _ in range(10):
            status = ib.get_order_status(order_id)
            if status:
                logger.info(f"Received status update: {status}")
                break
            time.sleep(1)
            
        # If we didn't get a status update after 10 seconds, try one more time
        if not status:
            logger.info("No status updates received. Trying one more time...")
            status = ib.wait_for_order_status(order_id, timeout=5)
            
        if status:
            logger.info(f"Final order status: {status}")
        else:
            logger.info("No status updates received for the order")
            
        # Check if order already exists in database
        try:
            db_order = Order.objects.get(order_id=str(order_id))
            logger.info(f"Order with ID {order_id} already exists in database. Updating...")
            
            # Update existing order
            if status:
                from ib_gateway.views import map_ib_status
                db_order.status = map_ib_status(status.get('status'))
                
                if status.get('filled', 0) > 0:
                    db_order.filled_quantity = status.get('filled')
                    
                if status.get('avgFillPrice', 0) > 0:
                    db_order.avg_fill_price = status.get('avgFillPrice')
                    
            db_order.save()
            logger.info(f"Order updated in database")
            
        except Order.DoesNotExist:
            # Create the order in the database
            db_order = Order(
                order_id=str(order_id),
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type=order_type,
                sec_type=sec_type,
                exchange=exchange,
                currency=currency,
                status="SUBMITTED"  # Initial status
            )
            
            # Update status and fill information if available
            if status:
                from ib_gateway.views import map_ib_status
                db_order.status = map_ib_status(status.get('status'))
                
                if status.get('filled', 0) > 0:
                    db_order.filled_quantity = status.get('filled')
                    
                if status.get('avgFillPrice', 0) > 0:
                    db_order.avg_fill_price = status.get('avgFillPrice')
                    
            # Save the order to the database
            db_order.save()
            logger.info(f"Order saved to database with ID {db_order.id}")
            
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
    finally:
        # Always disconnect
        logger.info("Disconnecting from IB Gateway")
        ib.disconnect()
        
if __name__ == "__main__":
    # Get command line arguments or use defaults
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    else:
        symbol = "AAPL"
        
    if len(sys.argv) > 2:
        action = sys.argv[2]
    else:
        action = "BUY"
        
    if len(sys.argv) > 3:
        try:
            quantity = float(sys.argv[3])
        except ValueError:
            quantity = 1
    else:
        quantity = 1
        
    if len(sys.argv) > 4:
        order_type = sys.argv[4]
    else:
        order_type = "MKT"
        
    place_order_to_ib(symbol, action, quantity, order_type) 