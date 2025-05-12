#!/usr/bin/env python
"""
Script to check IB Gateway connection
Run with: python check_connection.py
"""

import os
import sys
import django
import time
import logging
import argparse

# Set up Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inter_broker.settings')
django.setup()

from ib_gateway.connection import IBConnection

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_connection(host='127.0.0.1', port=4002, client_id=1, timeout=10):
    """Check connection to IB Gateway"""
    logger.info(f"Connecting to IB Gateway at {host}:{port} with client ID {client_id}")
    
    ib = IBConnection(host=host, port=port, client_id=client_id)
    connected = ib.connect()
    
    if connected:
        logger.info("✅ Successfully connected to IB Gateway")
        logger.info("Requesting account updates...")
        ib.request_account_updates()
        
        # Wait for data
        logger.info(f"Waiting up to {timeout} seconds for data...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if ib.api.account_info:
                accounts = list(ib.api.account_info.keys())
                logger.info(f"Received data for {len(accounts)} accounts: {accounts}")
                break
            time.sleep(0.5)
        else:
            logger.warning("No account data received within timeout")
            
        # Disconnect
        logger.info("Disconnecting...")
        ib.disconnect()
        logger.info("Disconnected from IB Gateway")
        return True
    else:
        logger.error("❌ Failed to connect to IB Gateway")
        logger.error("Please check that:")
        logger.error("1. IB Gateway is running")
        logger.error("2. API connections are enabled in IB Gateway settings")
        logger.error("3. The port number matches what's configured in IB Gateway")
        logger.error("4. No other applications are using the same client ID")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check connection to Interactive Brokers Gateway")
    parser.add_argument('--host', default='127.0.0.1', help='IB Gateway host address')
    parser.add_argument('--port', type=int, default=4002, help='IB Gateway port (4001 for live, 4002 for paper)')
    parser.add_argument('--client-id', type=int, default=1, help='Client ID for connection')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout in seconds for data to arrive')
    
    args = parser.parse_args()
    
    success = check_connection(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        timeout=args.timeout
    )
    
    sys.exit(0 if success else 1) 