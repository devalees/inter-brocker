from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
import threading
import time
import logging
import queue

logger = logging.getLogger(__name__)

class IBApi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.connected = False
        self.next_order_id = None
        self.account_info = {}
        self.order_status_updates = queue.Queue()
        self.execution_details = {}
        self.order_states = {}
        
    def error(self, reqId, errorCode, errorString):
        logger.error(f"Error {errorCode}: {errorString}")
        # TWS/IB Gateway can notify about connection status through error messages
        if errorCode == 502:  # Couldn't connect to TWS
            self.connected = False
        elif errorCode == 1100:  # Connectivity between IB and TWS has been lost
            self.connected = False
            
    def nextValidId(self, orderId):
        """Called when connection is established and an order ID is received"""
        logger.info(f"Next valid order ID: {orderId}")
        self.next_order_id = orderId
        self.connected = True
        
    def connectionClosed(self):
        """Called when connection is closed"""
        logger.info("IB Gateway connection closed")
        self.connected = False
        
    def updateAccountValue(self, key, val, currency, accountName):
        """Called when account information is updated"""
        logger.info(f"Account value updated: {key}={val} {currency} for {accountName}")
        if accountName not in self.account_info:
            self.account_info[accountName] = {}
        if key not in self.account_info[accountName]:
            self.account_info[accountName][key] = {}
        self.account_info[accountName][key][currency] = val
        
    def accountSummary(self, reqId, account, tag, value, currency):
        """Called when account summary data is received"""
        logger.info(f"Account summary: {account} {tag}={value} {currency}")
        
    def position(self, account, contract, position, avgCost):
        """Called when position information is received"""
        logger.info(f"Position: {account} - {contract.symbol} {position} @ {avgCost}")
    
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Called when order status changes"""
        logger.info(f"Order status update: Order {orderId} - Status: {status}, Filled: {filled}, Remaining: {remaining}, Avg Fill Price: {avgFillPrice}")
        
        # Store the order status info in a queue for processing
        update = {
            'orderId': str(orderId),
            'status': status,
            'filled': filled,
            'remaining': remaining,
            'avgFillPrice': avgFillPrice
        }
        self.order_status_updates.put(update)
        
        # Also store in order states dictionary
        self.order_states[str(orderId)] = update
    
    def execDetails(self, reqId, contract, execution):
        """Called when an order is executed"""
        logger.info(f"Execution: Order {execution.orderId} - {execution.shares} shares of {contract.symbol} @ {execution.price}")
        
        # Save execution details
        if str(execution.orderId) not in self.execution_details:
            self.execution_details[str(execution.orderId)] = []
        
        self.execution_details[str(execution.orderId)].append({
            'executionId': execution.execId,
            'time': execution.time,
            'account': execution.acctNumber,
            'exchange': execution.exchange,
            'side': execution.side,
            'shares': execution.shares,
            'price': execution.price,
            'permId': execution.permId,
            'clientId': execution.clientId,
            'liquidation': execution.liquidation
        })


class IBConnection:
    def __init__(self, host='127.0.0.1', port=4002, client_id=1):
        """
        Initialize IB connection
        
        Args:
            host (str): IB Gateway/TWS hostname or IP
            port (int): IB Gateway/TWS port (default: 4002 for IB Gateway paper trading)
            client_id (int): Client ID for this connection
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.api = IBApi()
        self.connection_thread = None
        
    def connect(self):
        """Connect to IB Gateway/TWS"""
        if self.api.connected:
            logger.info("Already connected to IB Gateway")
            return True
            
        logger.info(f"Connecting to IB Gateway at {self.host}:{self.port}")
        self.api.connect(self.host, self.port, self.client_id)
        
        # Launch the client thread
        self.connection_thread = threading.Thread(target=self._run_client, daemon=True)
        self.connection_thread.start()
        
        # Wait for connection to be established
        timeout = 10  # seconds
        start_time = time.time()
        while not self.api.connected and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if not self.api.connected:
            logger.error("Failed to connect to IB Gateway within timeout")
            return False
            
        logger.info("Successfully connected to IB Gateway")
        return True
        
    def disconnect(self):
        """Disconnect from IB Gateway/TWS"""
        if self.api.connected:
            self.api.disconnect()
            logger.info("Disconnected from IB Gateway")
            
    def _run_client(self):
        """Run the client message loop in a separate thread"""
        self.api.run()
        
    def is_connected(self):
        """Check if connected to IB Gateway/TWS"""
        return self.api.connected
        
    def request_account_updates(self, account=""):
        """Request account updates"""
        if not self.api.connected:
            logger.error("Not connected to IB Gateway")
            return False
            
        self.api.reqAccountUpdates(True, account)
        return True
        
    def create_contract(self, symbol, sec_type="STK", exchange="SMART", currency="USD", 
                        expiry="", strike=0.0, right="", multiplier="", local_symbol=""):
        """Create a contract object"""
        contract = Contract()
        contract.symbol = symbol
        contract.secType = sec_type
        contract.exchange = exchange
        contract.currency = currency
        
        if expiry:
            contract.lastTradeDateOrContractMonth = expiry
        if strike != 0.0:
            contract.strike = strike
        if right:
            contract.right = right
        if multiplier:
            contract.multiplier = multiplier
        if local_symbol:
            contract.localSymbol = local_symbol
            
        return contract
        
    def create_order(self, action, quantity, order_type="MKT", limit_price=0.0, stop_price=0.0):
        """Create an order object"""
        if not self.api.next_order_id:
            logger.error("No valid order ID available")
            return None
            
        order = Order()
        order.action = action  # "BUY" or "SELL"
        order.totalQuantity = quantity
        order.orderType = order_type  # "MKT", "LMT", "STP", etc.
        
        if order_type == "LMT" and limit_price > 0:
            order.lmtPrice = limit_price
        elif order_type == "STP" and stop_price > 0:
            order.auxPrice = stop_price
            
        # Ensure no unsupported attributes are set
        if hasattr(order, 'eTradeOnly'):
            order.eTradeOnly = False
            
        if hasattr(order, 'firmQuoteOnly'):
            order.firmQuoteOnly = False
            
        # Set other attributes to sensible defaults
        order.outsideRth = False  # Allow execution outside regular trading hours
        order.tif = "GTC"  # Good Till Canceled
            
        return order
        
    def place_order(self, contract, order):
        """Place an order with IB"""
        if not self.api.connected:
            logger.error("Not connected to IB Gateway")
            return False
            
        if not self.api.next_order_id:
            logger.error("No valid order ID available")
            return False
            
        order_id = self.api.next_order_id
        self.api.next_order_id += 1
        
        logger.info(f"Placing order {order_id} - {order.action} {order.totalQuantity} {contract.symbol}")
        self.api.placeOrder(order_id, contract, order)
        return order_id

    def wait_for_order_status(self, order_id, timeout=10):
        """
        Wait for order status updates for a specific order
        
        Args:
            order_id (str): Order ID to wait for
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            dict: Order status information or None if timeout
        """
        order_id = str(order_id)
        start_time = time.time()
        
        # Check if we already have a status for this order
        if order_id in self.api.order_states:
            return self.api.order_states[order_id]
        
        # Wait for status updates
        while time.time() - start_time < timeout:
            try:
                # Check for updates in the queue
                update = self.api.order_status_updates.get(block=True, timeout=0.5)
                
                # If this is the order we're waiting for, return the update
                if update['orderId'] == order_id:
                    return update
                    
            except queue.Empty:
                # No updates in the queue, continue waiting
                time.sleep(0.1)
                
        # Timeout reached, check one more time
        if order_id in self.api.order_states:
            return self.api.order_states[order_id]
            
        return None
            
    def get_order_status(self, order_id):
        """
        Get the current status of an order
        
        Args:
            order_id (str): Order ID to check
            
        Returns:
            dict: Order status information or None if not found
        """
        order_id = str(order_id)
        return self.api.order_states.get(order_id, None)
        
    def get_execution_details(self, order_id):
        """
        Get execution details for an order
        
        Args:
            order_id (str): Order ID to check
            
        Returns:
            list: List of execution details or empty list if none
        """
        order_id = str(order_id)
        return self.api.execution_details.get(order_id, [])


# Function to test connection
def test_connection(host='127.0.0.1', port=4002, client_id=1):
    """
    Test connection to IB Gateway
    
    Returns:
        tuple: (success, message)
    """
    ib = IBConnection(host, port, client_id)
    if ib.connect():
        # Test requesting account information
        ib.request_account_updates()
        time.sleep(2)  # Wait a bit for data to arrive
        accounts = ib.api.account_info
        ib.disconnect()
        return True, f"Connected successfully. Found {len(accounts)} accounts."
    else:
        return False, "Failed to connect to IB Gateway. Please make sure it's running and properly configured." 