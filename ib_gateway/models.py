from django.db import models


class IBConfig(models.Model):
    """Configuration for IB Gateway connection"""
    host = models.CharField(max_length=255, default='127.0.0.1', help_text="IB Gateway host address")
    port = models.IntegerField(default=4002, help_text="IB Gateway port (4001 for live, 4002 for paper)")
    client_id = models.IntegerField(default=1, help_text="Client ID for connection")
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "IB Gateway Configuration"
        verbose_name_plural = "IB Gateway Configurations"
        
    def __str__(self):
        return f"IB Gateway Config: {self.host}:{self.port} (Client ID: {self.client_id})"


class Order(models.Model):
    """IB Order record"""
    ORDER_STATUSES = [
        ('SUBMITTED', 'Submitted'),
        ('ACCEPTED', 'Accepted'),
        ('FILLED', 'Filled'),
        ('CANCELLED', 'Cancelled'),
        ('REJECTED', 'Rejected'),
        ('PENDING', 'Pending'),
    ]
    
    ORDER_TYPES = [
        ('MKT', 'Market'),
        ('LMT', 'Limit'),
        ('STP', 'Stop'),
        ('STP_LMT', 'Stop Limit'),
    ]
    
    ACTIONS = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]
    
    order_id = models.CharField(max_length=50, unique=True, help_text="IB Order ID")
    action = models.CharField(max_length=10, choices=ACTIONS, help_text="Buy or Sell")
    symbol = models.CharField(max_length=20, help_text="Ticker symbol")
    sec_type = models.CharField(max_length=10, default="STK", help_text="Security type (STK, OPT, FUT, CASH)")
    exchange = models.CharField(max_length=20, default="SMART", help_text="Exchange")
    currency = models.CharField(max_length=3, default="USD", help_text="Currency")
    quantity = models.DecimalField(max_digits=15, decimal_places=5, help_text="Order quantity")
    order_type = models.CharField(max_length=10, choices=ORDER_TYPES, default="MKT", help_text="Order type")
    limit_price = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True, help_text="Limit price if applicable")
    stop_price = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True, help_text="Stop price if applicable")
    status = models.CharField(max_length=20, choices=ORDER_STATUSES, default='PENDING', help_text="Order status")
    filled_quantity = models.DecimalField(max_digits=15, decimal_places=5, default=0, help_text="Quantity filled")
    avg_fill_price = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True, help_text="Average fill price")
    webhook = models.ForeignKey('broker.Webhook', on_delete=models.SET_NULL, null=True, blank=True, help_text="Related webhook that triggered this order")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "IB Order"
        verbose_name_plural = "IB Orders"
        ordering = ['-created_at']
        
    def __str__(self):
        return f"Order {self.order_id}: {self.action} {self.quantity} {self.symbol} @ {self.order_type}" 