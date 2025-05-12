from django.core.management.base import BaseCommand
from ib_gateway.connection import IBConnection
import time
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Check the connection to IB Gateway'
    
    def add_arguments(self, parser):
        parser.add_argument('--host', default='127.0.0.1', help='IB Gateway host address')
        parser.add_argument('--port', type=int, default=4002, help='IB Gateway port (4001 for live, 4002 for paper)')
        parser.add_argument('--client-id', type=int, default=1, help='Client ID for connection')
        parser.add_argument('--timeout', type=int, default=10, help='Timeout in seconds for data to arrive')
    
    def handle(self, *args, **options):
        host = options['host']
        port = options['port']
        client_id = options['client_id']
        timeout = options['timeout']
        
        self.stdout.write(self.style.NOTICE(f"Connecting to IB Gateway at {host}:{port} with client ID {client_id}"))
        
        ib = IBConnection(host=host, port=port, client_id=client_id)
        connected = ib.connect()
        
        if connected:
            self.stdout.write(self.style.SUCCESS("✅ Successfully connected to IB Gateway"))
            self.stdout.write(self.style.NOTICE("Requesting account updates..."))
            ib.request_account_updates()
            
            # Wait for data
            self.stdout.write(self.style.NOTICE(f"Waiting up to {timeout} seconds for data..."))
            start_time = time.time()
            while time.time() - start_time < timeout:
                if ib.api.account_info:
                    accounts = list(ib.api.account_info.keys())
                    self.stdout.write(self.style.SUCCESS(f"Received data for {len(accounts)} accounts: {accounts}"))
                    break
                time.sleep(0.5)
            else:
                self.stdout.write(self.style.WARNING("No account data received within timeout"))
                
            # Disconnect
            self.stdout.write(self.style.NOTICE("Disconnecting..."))
            ib.disconnect()
            self.stdout.write(self.style.SUCCESS("Disconnected from IB Gateway"))
        else:
            self.stdout.write(self.style.ERROR("❌ Failed to connect to IB Gateway"))
            self.stdout.write(self.style.ERROR("Please check that:"))
            self.stdout.write(self.style.ERROR("1. IB Gateway is running"))
            self.stdout.write(self.style.ERROR("2. API connections are enabled in IB Gateway settings"))
            self.stdout.write(self.style.ERROR("3. The port number matches what's configured in IB Gateway"))
            self.stdout.write(self.style.ERROR("4. No other applications are using the same client ID")) 