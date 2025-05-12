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

def get_orders_from_ib_directly():
    """Query orders directly from IB Gateway"""
    
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
        # Set up the wrapper to handle opened orders 
        orders_received = []
        
        # Store the original methods
        original_openOrder = ib.api.openOrder
        original_openOrderEnd = ib.api.openOrderEnd
        
        # Create a handler for openOrder events
        def handle_open_order(orderId, contract, order, orderState):
            logger.info(f"Received open order: {orderId}")
            orders_received.append({
                'orderId': orderId,
                'symbol': contract.symbol,
                'secType': contract.secType,
                'exchange': contract.exchange,
                'currency': contract.currency,
                'action': order.action,
                'quantity': order.totalQuantity,
                'orderType': order.orderType,
                'status': orderState.status,
                'filled': orderState.filled if hasattr(orderState, 'filled') else 0,
                'remaining': orderState.remaining if hasattr(orderState, 'remaining') else 0,
                'avgFillPrice': orderState.avgFillPrice if hasattr(orderState, 'avgFillPrice') else 0,
            })
            
            # Call the original method if it exists
            if original_openOrder is not None:
                original_openOrder(orderId, contract, order, orderState)
        
        # Create a handler for openOrderEnd events
        def handle_open_order_end():
            logger.info(f"Open orders request completed. Received {len(orders_received)} orders.")
            # Call the original method if it exists
            if original_openOrderEnd is not None:
                original_openOrderEnd()
        
        # Replace the methods
        ib.api.openOrder = handle_open_order
        ib.api.openOrderEnd = handle_open_order_end
        
        # Request open orders
        logger.info("Requesting open orders from IB Gateway...")
        ib.api.reqOpenOrders()
        
        # Wait for data to be received
        time.sleep(3)
        
        # Print the received orders
        if orders_received:
            logger.info(f"Retrieved {len(orders_received)} orders from IB Gateway:")
            for order in orders_received:
                logger.info(f"Order ID: {order['orderId']}")
                logger.info(f"  Symbol: {order['symbol']}")
                logger.info(f"  Action: {order['action']}")
                logger.info(f"  Quantity: {order['quantity']}")
                logger.info(f"  Order Type: {order['orderType']}")
                logger.info(f"  Status: {order['status']}")
                logger.info(f"  Filled: {order['filled']}")
                logger.info(f"  Remaining: {order['remaining']}")
                logger.info(f"  Avg Fill Price: {order['avgFillPrice']}")
                logger.info("  ---")
        else:
            logger.info("No open orders found in IB Gateway")
            
        # Request all executions for today
        logger.info("\nRequesting executions for today...")
        
        # Store executions
        executions_received = []
        
        # Store the original execDetails method
        original_execDetails = ib.api.execDetails
        
        # Create a handler for execution details
        def handle_exec_details(reqId, contract, execution):
            logger.info(f"Received execution details for order {execution.orderId}")
            executions_received.append({
                'orderId': execution.orderId,
                'execId': execution.execId,
                'time': execution.time,
                'symbol': contract.symbol,
                'secType': contract.secType,
                'exchange': execution.exchange,
                'side': execution.side,
                'shares': execution.shares,
                'price': execution.price,
                'account': execution.acctNumber
            })
            
            # Call the original method if it exists
            if original_execDetails is not None:
                original_execDetails(reqId, contract, execution)
        
        # Replace the execDetails method
        ib.api.execDetails = handle_exec_details
        
        # Request executions
        from datetime import datetime
        # Format: YYYYMMDD-HH:MM:SS (with no timezone = UTC)
        today = datetime.now().strftime("%Y%m%d-%H:%M:%S")
        
        # Create an empty execution filter to get all executions
        from ibapi.execution import ExecutionFilter
        exec_filter = ExecutionFilter()
        exec_filter.clientId = config.client_id
        # Leave time field empty to get all executions
        exec_filter.time = ""
        
        # Request executions
        ib.api.reqExecutions(1, exec_filter)
        
        # Wait for data to be received
        time.sleep(3)
        
        # Print the received executions
        if executions_received:
            logger.info(f"Retrieved {len(executions_received)} executions from IB Gateway:")
            for exec_detail in executions_received:
                logger.info(f"Order ID: {exec_detail['orderId']}")
                logger.info(f"  Exec ID: {exec_detail['execId']}")
                logger.info(f"  Time: {exec_detail['time']}")
                logger.info(f"  Symbol: {exec_detail['symbol']}")
                logger.info(f"  Side: {exec_detail['side']}")
                logger.info(f"  Shares: {exec_detail['shares']}")
                logger.info(f"  Price: {exec_detail['price']}")
                logger.info(f"  Account: {exec_detail['account']}")
                logger.info("  ---")
        else:
            logger.info("No executions found in IB Gateway")
            
        # Compare with orders in the database
        logger.info("\nComparing with orders in the database...")
        db_orders = Order.objects.all().order_by('-created_at')
        
        for db_order in db_orders:
            if not db_order.order_id:
                continue
                
            # Check if this order is in the IB Gateway results
            found = False
            for ib_order in orders_received:
                if str(ib_order['orderId']) == db_order.order_id:
                    found = True
                    logger.info(f"Order {db_order.order_id} found in both DB and IB Gateway")
                    
                    # Check for status mismatch
                    from ib_gateway.views import map_ib_status
                    mapped_status = map_ib_status(ib_order['status'])
                    if mapped_status != db_order.status:
                        logger.info(f"  Status mismatch! DB: {db_order.status}, IB: {mapped_status}")
                        
                    # Check for filled quantity mismatch
                    if float(ib_order['filled']) != float(db_order.filled_quantity or 0):
                        logger.info(f"  Filled quantity mismatch! DB: {db_order.filled_quantity}, IB: {ib_order['filled']}")
                    break
                    
            if not found:
                logger.info(f"Order {db_order.order_id} found in DB but not in IB Gateway")
                
                # Look for executions related to this order
                for exec_detail in executions_received:
                    if str(exec_detail['orderId']) == db_order.order_id:
                        logger.info(f"  But found execution for this order: {exec_detail['shares']} @ {exec_detail['price']}")
                
    except Exception as e:
        logger.error(f"Error querying orders: {str(e)}")
    finally:
        # Always disconnect
        logger.info("Disconnecting from IB Gateway")
        ib.disconnect()

if __name__ == "__main__":
    get_orders_from_ib_directly() 