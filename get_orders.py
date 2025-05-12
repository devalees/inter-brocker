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

def get_orders_from_ib():
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
        # Fetch orders from the database first
        db_orders = Order.objects.all().order_by('-created_at')
        logger.info(f"Found {db_orders.count()} orders in the database:")
        
        for order in db_orders:
            logger.info(f"Order ID: {order.order_id}")
            logger.info(f"  Symbol: {order.symbol}")
            logger.info(f"  Action: {order.action}")
            logger.info(f"  Quantity: {order.quantity}")
            logger.info(f"  Order Type: {order.order_type}")
            logger.info(f"  Status: {order.status}")
            logger.info(f"  Filled Quantity: {order.filled_quantity}")
            logger.info(f"  Avg Fill Price: {order.avg_fill_price}")
            logger.info(f"  Created At: {order.created_at}")
            
            # Fetch the latest status from IB if order has an order_id
            if order.order_id:
                status = ib.get_order_status(order.order_id)
                executions = ib.get_execution_details(order.order_id)
                
                logger.info(f"  IB Status: {status if status else 'Not found in IB'}")
                if executions:
                    logger.info(f"  Executions: {len(executions)}")
                    for exec_detail in executions:
                        logger.info(f"    Time: {exec_detail.get('time')}, Shares: {exec_detail.get('shares')}, Price: {exec_detail.get('price')}")
            
            # Get updated status from IB
            if order.order_id:
                # Request real-time status update
                updated_status = ib.wait_for_order_status(order.order_id, timeout=2)
                if updated_status:
                    logger.info(f"  Updated Status: {updated_status.get('status')}")
                    logger.info(f"  Updated Filled: {updated_status.get('filled')}")
                    logger.info(f"  Updated Remaining: {updated_status.get('remaining')}")
                    logger.info(f"  Updated Avg Fill Price: {updated_status.get('avgFillPrice')}")
                    
                    # Compare with database status
                    if updated_status.get('status') != order.status:
                        logger.info(f"  Status mismatch! DB: {order.status}, IB: {updated_status.get('status')}")
                    
                    if float(updated_status.get('filled', 0)) != float(order.filled_quantity or 0):
                        logger.info(f"  Filled quantity mismatch! DB: {order.filled_quantity}, IB: {updated_status.get('filled')}")
            
            logger.info("  ---")
        
        # Check if any orders need to be updated in the database
        logger.info("\nChecking for orders that need database updates...")
        updated_count = 0
        
        for order in db_orders:
            if not order.order_id:
                continue
                
            status = ib.get_order_status(order.order_id)
            if not status:
                continue
                
            needs_update = False
            
            # Check if status needs updating
            from ib_gateway.views import map_ib_status
            mapped_status = map_ib_status(status.get('status'))
            if mapped_status != order.status:
                logger.info(f"Order {order.order_id} status change: {order.status} -> {mapped_status}")
                order.status = mapped_status
                needs_update = True
            
            # Check if filled quantity needs updating
            if float(status.get('filled', 0)) != float(order.filled_quantity or 0):
                logger.info(f"Order {order.order_id} filled change: {order.filled_quantity} -> {status.get('filled')}")
                order.filled_quantity = status.get('filled')
                needs_update = True
                
            # Check if avg fill price needs updating
            if float(status.get('avgFillPrice', 0)) != float(order.avg_fill_price or 0):
                logger.info(f"Order {order.order_id} avg price change: {order.avg_fill_price} -> {status.get('avgFillPrice')}")
                order.avg_fill_price = status.get('avgFillPrice')
                needs_update = True
                
            if needs_update:
                order.save()
                updated_count += 1
                
        if updated_count > 0:
            logger.info(f"Updated {updated_count} orders in the database")
        else:
            logger.info("No orders needed database updates")
            
    except Exception as e:
        logger.error(f"Error querying orders: {str(e)}")
    finally:
        # Always disconnect
        logger.info("Disconnecting from IB Gateway")
        ib.disconnect()

if __name__ == "__main__":
    get_orders_from_ib() 