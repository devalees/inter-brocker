from django.contrib import admin
from django import forms
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from .models import IBConfig, Order
from .connection import IBConnection
from .views import map_ib_status
import logging
import decimal
import time
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.contrib import messages

logger = logging.getLogger(__name__)


@admin.register(IBConfig)
class IBConfigAdmin(admin.ModelAdmin):
    list_display = ('host', 'port', 'client_id', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('host',)


class OrderAdminForm(forms.ModelForm):
    """Custom form for Order admin to handle order submission to IB Gateway"""
    
    submit_to_ib = forms.BooleanField(
        label="Submit to IB Gateway",
        required=False,
        initial=True,
        help_text="Uncheck if you only want to save without submitting to IB Gateway"
    )
    
    class Meta:
        model = Order
        fields = '__all__'
        exclude = ('status', 'filled_quantity', 'avg_fill_price')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        
        # If this is an existing order (edit mode), disable submitting to IB
        if instance and instance.pk:
            self.fields['submit_to_ib'].initial = False
            self.fields['submit_to_ib'].disabled = True
            self.fields['submit_to_ib'].help_text = "Orders can't be resubmitted once created"
            
            # Make key contract fields read-only when editing
            for field in ['symbol', 'action', 'quantity', 'order_type', 'sec_type', 'exchange', 'currency']:
                if field in self.fields:
                    self.fields[field].disabled = True
                    

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    
    list_display = ('order_id', 'action', 'symbol', 'quantity', 'order_type', 'get_ib_status', 'filled_quantity', 'created_at')
    list_filter = ('action', 'status', 'order_type', 'created_at')
    search_fields = ('order_id', 'symbol')
    readonly_fields = ('order_id', 'filled_quantity', 'avg_fill_price', 'status', 'created_at', 'updated_at')
    
    # Define fieldsets for adding a new order
    add_fieldsets = (
        (None, {
            'fields': ('submit_to_ib',)
        }),
        ('Contract Details', {
            'fields': ('symbol', 'sec_type', 'exchange', 'currency')
        }),
        ('Order Details', {
            'fields': ('action', 'quantity', 'order_type', 'limit_price', 'stop_price')
        }),
        ('References', {
            'fields': ('webhook',)
        }),
    )
    
    # Define fieldsets for viewing/editing an existing order
    change_fieldsets = (
        ('Contract Details', {
            'fields': ('symbol', 'sec_type', 'exchange', 'currency')
        }),
        ('Order Details', {
            'fields': ('action', 'quantity', 'order_type', 'limit_price', 'stop_price')
        }),
        ('Status & Results', {
            'fields': ('order_id', 'status', 'filled_quantity', 'avg_fill_price')
        }),
        ('References', {
            'fields': ('webhook',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    # Add a custom action button to fetch all orders
    change_list_template = 'admin/ib_gateway/order_changelist.html'
    
    # Add action buttons for order refresh
    actions = ['refresh_order_status', 'fetch_all_orders_from_ib']
    
    def get_fieldsets(self, request, obj=None):
        """Return different fieldsets for add and change views"""
        if obj is None:  # Adding a new order
            return self.add_fieldsets
        return self.change_fieldsets
    
    def get_readonly_fields(self, request, obj=None):
        """Make only specific fields readonly based on whether this is a new or existing order"""
        if obj:  # Editing existing object
            return self.readonly_fields
        else:  # New object
            return ('created_at', 'updated_at')  # Only make timestamps readonly
    
    def get_form(self, request, obj=None, **kwargs):
        """Customize the form based on whether this is a create or update"""
        form = super().get_form(request, obj, **kwargs)
        return form
        
    def save_model(self, request, obj, form, change):
        """Override save_model to handle IB Gateway submission"""
        # Set default values for fields not in the form
        if not change:
            obj.status = 'PENDING'  # Set initial status
        
        # If this is a new order and we want to submit to IB
        if not change and form.cleaned_data.get('submit_to_ib'):
            self._submit_to_ib_gateway(obj)
        else:
            # Just save to database without IB submission
            super().save_model(request, obj, form, change)
    
    def _submit_to_ib_gateway(self, order_obj):
        """Submit the order to IB Gateway"""
        try:
            # Get the active configuration
            config = IBConfig.objects.filter(is_active=True).first()
            if not config:
                raise Exception("No active IB Gateway configuration found")
                
            # Connect to IB Gateway
            ib = IBConnection(config.host, config.port, config.client_id)
            if not ib.connect():
                raise Exception("Failed to connect to IB Gateway")
                
            try:
                # Create contract
                contract = ib.create_contract(
                    symbol=order_obj.symbol,
                    sec_type=order_obj.sec_type,
                    exchange=order_obj.exchange,
                    currency=order_obj.currency
                )
                
                # Create order
                order_args = {
                    'action': order_obj.action,
                    'quantity': float(order_obj.quantity),
                    'order_type': order_obj.order_type
                }
                
                if order_obj.limit_price and order_obj.order_type in ('LMT', 'STP_LMT'):
                    order_args['limit_price'] = float(order_obj.limit_price)
                    
                if order_obj.stop_price and order_obj.order_type in ('STP', 'STP_LMT'):
                    order_args['stop_price'] = float(order_obj.stop_price)
                    
                # Use IB's next valid order ID
                if not ib.api.next_order_id:
                    raise Exception("No valid order ID available from IB Gateway")
                
                # Create IB order object
                ib_order = ib.create_order(**order_args)
                
                if not ib_order:
                    raise Exception("Failed to create order")
                    
                # Place the order
                order_id = ib.place_order(contract, ib_order)
                
                if not order_id:
                    raise Exception("Failed to place order")
                    
                # Update our order object with the IB order ID
                order_obj.order_id = str(order_id)
                order_obj.status = 'SUBMITTED'
                
                # Save the order to get an ID
                order_obj.save()
                
                # Wait for initial order status update with more retries
                logger.info(f"Waiting for order status for order {order_id}")
                
                # Try multiple times to get the status update
                # Market orders often fill quickly, but we need to poll a few times
                max_attempts = 5
                attempt = 0
                filled = False
                
                while attempt < max_attempts and not filled:
                    attempt += 1
                    logger.info(f"Checking order status attempt {attempt}/{max_attempts}")
                    # Wait for status update
                    order_status = ib.wait_for_order_status(order_id, timeout=3)
                    
                    if order_status:
                        logger.info(f"Received order status: {order_status}")
                        # Update the order in the database
                        status_name = map_ib_status(order_status['status'])
                        order_obj.status = status_name
                        
                        if order_status['filled'] > 0:
                            order_obj.filled_quantity = decimal.Decimal(order_status['filled'])
                            
                        if order_status['avgFillPrice'] > 0:
                            order_obj.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                            
                        # Save the updated order
                        order_obj.save()
                        
                        # If the order is filled completely, break the loop
                        if status_name == 'FILLED' or float(order_status['filled']) >= float(order_obj.quantity):
                            logger.info(f"Order {order_id} is filled, no need to check again")
                            filled = True
                            break
                    
                    # Wait for a moment before retrying
                    if not filled and attempt < max_attempts:
                        time.sleep(2)  # Wait 2 seconds between attempts
                
            finally:
                # Always disconnect from IB Gateway
                ib.disconnect()
                
        except Exception as e:
            # Log the error
            logger.error(f"Error submitting order to IB Gateway: {str(e)}")
            # Still save the order, but mark it as rejected
            order_obj.status = 'REJECTED'
            order_obj.save()
            # Re-raise the exception to show in admin
            raise
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of orders that have been submitted"""
        if obj and obj.order_id:
            return False  # Prevent deletion of orders that have an order_id
        return super().has_delete_permission(request, obj)
    
    def refresh_order_status(self, request, queryset):
        """Action to refresh the status of selected orders"""
        updated = 0
        errors = []
        
        for order in queryset:
            if not order.order_id:
                continue
                
            try:
                # Get the active configuration
                config = IBConfig.objects.filter(is_active=True).first()
                if not config:
                    self.message_user(request, "No active IB Gateway configuration found", level='ERROR')
                    return
                    
                # Connect to IB Gateway
                ib = IBConnection(config.host, config.port, config.client_id)
                if not ib.connect():
                    self.message_user(request, "Failed to connect to IB Gateway", level='ERROR')
                    return
                    
                try:
                    # Check order status
                    order_status = ib.wait_for_order_status(order.order_id, timeout=3)
                    
                    if order_status:
                        # Update the order in the database
                        status_name = map_ib_status(order_status['status'])
                        old_status = order.status
                        order.status = status_name
                        
                        if order_status['filled'] > 0:
                            order.filled_quantity = decimal.Decimal(order_status['filled'])
                            
                        if order_status['avgFillPrice'] > 0:
                            order.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                            
                        order.save()
                        updated += 1
                    
                finally:
                    # Always disconnect from IB Gateway
                    ib.disconnect()
                    
            except Exception as e:
                # Special handling for duplicate order ID errors
                error_message = str(e)
                if "Duplicate order id" in error_message or "duplicate order id" in error_message.lower():
                    errors.append(f"Order {order.order_id} could not be refreshed: IB Gateway reported duplicate order ID. This order ID may be conflicting with another order.")
                else:
                    # Log the error
                    logger.error(f"Error refreshing order {order.order_id}: {str(e)}")
                    errors.append(f"Error refreshing order {order.order_id}: {str(e)}")
        
        if updated > 0:
            self.message_user(request, f"Successfully updated {updated} orders", level='SUCCESS')
        else:
            self.message_user(request, "No orders were updated", level='WARNING')
            
        # Report any errors
        for error in errors:
            self.message_user(request, error, level='ERROR')
    
    refresh_order_status.short_description = "Refresh order status from IB Gateway"
    
    def fetch_all_orders_from_ib(self, request, queryset):
        """Fetch all orders from IB Gateway and sync with database"""
        try:
            # Get the active configuration
            config = IBConfig.objects.filter(is_active=True).first()
            if not config:
                self.message_user(request, "No active IB Gateway configuration found", level='ERROR')
                return
                
            # Connect to IB Gateway
            ib = IBConnection(config.host, config.port, config.client_id)
            if not ib.connect():
                self.message_user(request, "Failed to connect to IB Gateway", level='ERROR')
                return
                
            try:
                # Set up the wrapper to handle opened orders
                orders_received = []
                executions_received = []
                
                # Store the original methods
                original_openOrder = ib.api.openOrder
                original_openOrderEnd = ib.api.openOrderEnd
                original_execDetails = ib.api.execDetails
                
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
                
                # Replace the methods
                ib.api.openOrder = handle_open_order
                ib.api.openOrderEnd = handle_open_order_end
                ib.api.execDetails = handle_exec_details
                
                # Request open orders
                logger.info("Requesting open orders from IB Gateway...")
                ib.api.reqOpenOrders()
                
                # Wait for data to be received
                time.sleep(3)
                
                # Request executions
                from ibapi.execution import ExecutionFilter
                exec_filter = ExecutionFilter()
                exec_filter.clientId = config.client_id
                exec_filter.time = ""  # Empty string gets all executions
                
                # Request executions
                ib.api.reqExecutions(1, exec_filter)
                
                # Wait for data to be received
                time.sleep(3)
                
                # Process the results
                created_count = 0
                updated_count = 0
                execution_matched = 0
                
                # First, process open orders
                for ib_order in orders_received:
                    order_id = str(ib_order['orderId'])
                    
                    # Check if this order exists in our database
                    try:
                        db_order = Order.objects.get(order_id=order_id)
                        
                        # Update the existing order
                        db_order.symbol = ib_order['symbol']
                        db_order.action = ib_order['action']
                        db_order.sec_type = ib_order['secType']
                        db_order.exchange = ib_order['exchange']
                        db_order.currency = ib_order['currency']
                        db_order.quantity = ib_order['quantity']
                        db_order.order_type = ib_order['orderType']
                        db_order.status = map_ib_status(ib_order['status'])
                        db_order.filled_quantity = ib_order['filled']
                        db_order.avg_fill_price = ib_order['avgFillPrice']
                        db_order.save()
                        
                        updated_count += 1
                        
                    except Order.DoesNotExist:
                        # Create a new order in our database
                        db_order = Order(
                            order_id=order_id,
                            symbol=ib_order['symbol'],
                            action=ib_order['action'],
                            sec_type=ib_order['secType'],
                            exchange=ib_order['exchange'],
                            currency=ib_order['currency'],
                            quantity=ib_order['quantity'],
                            order_type=ib_order['orderType'],
                            status=map_ib_status(ib_order['status']),
                            filled_quantity=ib_order['filled'],
                            avg_fill_price=ib_order['avgFillPrice']
                        )
                        db_order.save()
                        
                        created_count += 1
                
                # Next, process executions for orders not found in openOrders
                for exec_detail in executions_received:
                    order_id = str(exec_detail['orderId'])
                    
                    # Skip if we already processed this order
                    if any(str(order['orderId']) == order_id for order in orders_received):
                        continue
                        
                    # Check if this order exists in our database
                    try:
                        db_order = Order.objects.get(order_id=order_id)
                        
                        # Update the existing order with execution details
                        if float(db_order.filled_quantity or 0) < float(exec_detail['shares']):
                            db_order.filled_quantity = exec_detail['shares']
                            db_order.avg_fill_price = exec_detail['price']
                            db_order.status = 'FILLED'
                            db_order.save()
                            
                            execution_matched += 1
                            
                    except Order.DoesNotExist:
                        # Create a new order based on execution
                        action = 'BUY' if exec_detail['side'] == 'BOT' else 'SELL'
                        db_order = Order(
                            order_id=order_id,
                            symbol=exec_detail['symbol'],
                            action=action,
                            sec_type=exec_detail['secType'],
                            exchange=exec_detail['exchange'],
                            currency='USD',  # Default
                            quantity=exec_detail['shares'],
                            order_type='MKT',  # Assume market
                            status='FILLED',
                            filled_quantity=exec_detail['shares'],
                            avg_fill_price=exec_detail['price']
                        )
                        db_order.save()
                        
                        created_count += 1
                
                # Prepare message
                message_parts = []
                if orders_received:
                    message_parts.append(f"Found {len(orders_received)} open orders in IB Gateway")
                if executions_received:
                    message_parts.append(f"Found {len(executions_received)} executions in IB Gateway")
                if created_count > 0:
                    message_parts.append(f"Created {created_count} new orders")
                if updated_count > 0:
                    message_parts.append(f"Updated {updated_count} existing orders")
                if execution_matched > 0:
                    message_parts.append(f"Updated {execution_matched} orders with execution details")
                    
                if message_parts:
                    self.message_user(request, ". ".join(message_parts), level='SUCCESS')
                else:
                    self.message_user(request, "No orders found in IB Gateway", level='WARNING')
                    
            finally:
                # Always disconnect from IB Gateway
                ib.disconnect()
                
        except Exception as e:
            logger.error(f"Error fetching orders from IB Gateway: {str(e)}")
            self.message_user(request, f"Error fetching orders from IB Gateway: {str(e)}", level='ERROR')
            
    fetch_all_orders_from_ib.short_description = "Fetch all orders from IB Gateway"
    
    def get_ib_status(self, obj):
        """Get real-time status from IB Gateway"""
        if not obj.order_id:
            return obj.status
        
        # Create connection object - but don't actually connect unless the user clicks the value
        status_html = f'<span>{obj.status}</span>'
        if obj.status != 'FILLED' and obj.status != 'CANCELLED' and obj.status != 'REJECTED':
            refresh_url = f'/admin/ib_gateway/order/{obj.id}/refresh_status/'
            status_html += f' <a href="{refresh_url}" class="button" style="padding: 0 5px; margin-left: 5px;">↻</a>'
        
        return format_html(status_html)
    
    get_ib_status.short_description = 'Status'
    get_ib_status.admin_order_field = 'status'
    
    def get_urls(self):
        """Add custom URLs for order operations"""
        urls = super().get_urls()
        from django.urls import path
        custom_urls = [
            path(
                '<path:object_id>/refresh_status/',
                self.admin_site.admin_view(self.refresh_single_order_view),
                name='ib_gateway_order_refresh_status',
            ),
            path(
                'fetch-all-orders/',
                self.admin_site.admin_view(self.fetch_all_orders_view),
                name='ib_gateway_fetch_all_orders',
            ),
        ]
        return custom_urls + urls
    
    def fetch_all_orders_view(self, request):
        """View to fetch all orders from IB Gateway"""
        # Call the fetch_all_orders_from_ib method with an empty queryset
        self.fetch_all_orders_from_ib(request, Order.objects.none())
        
        # Redirect back to the order list
        return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist'))
        
    def refresh_single_order_view(self, request, object_id):
        """View to refresh a single order's status"""
        # Get the order object
        order = self.get_object(request, object_id)
        if not order:
            return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist'))
            
        if not order.order_id:
            self.message_user(request, "Order has no IB Gateway order ID", level='ERROR')
            return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist'))
            
        try:
            # Get the active configuration
            config = IBConfig.objects.filter(is_active=True).first()
            if not config:
                self.message_user(request, "No active IB Gateway configuration found", level='ERROR')
                return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist'))
                
            # Connect to IB Gateway
            ib = IBConnection(config.host, config.port, config.client_id)
            if not ib.connect():
                self.message_user(request, "Failed to connect to IB Gateway", level='ERROR')
                return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist'))
                
            try:
                # Check order status
                order_status = ib.wait_for_order_status(order.order_id, timeout=3)
                
                if order_status:
                    # Update the order in the database
                    status_name = map_ib_status(order_status['status'])
                    old_status = order.status
                    order.status = status_name
                    
                    if order_status['filled'] > 0:
                        order.filled_quantity = decimal.Decimal(order_status['filled'])
                        
                    if order_status['avgFillPrice'] > 0:
                        order.avg_fill_price = decimal.Decimal(order_status['avgFillPrice'])
                        
                    order.save()
                    self.message_user(request, f"Successfully updated order {order.order_id} status to {status_name}", level='SUCCESS')
                else:
                    self.message_user(request, f"Order {order.order_id} not found in IB Gateway or no status available", level='WARNING')
                
            finally:
                # Always disconnect from IB Gateway
                ib.disconnect()
                
        except Exception as e:
            # Special handling for duplicate order ID errors
            error_message = str(e)
            if "Duplicate order id" in error_message or "duplicate order id" in error_message.lower():
                self.message_user(request, f"Order {order.order_id} could not be refreshed: IB Gateway reported duplicate order ID", level='ERROR')
            else:
                # Log the error
                logger.error(f"Error refreshing order {order.order_id}: {str(e)}")
                self.message_user(request, f"Error refreshing order {order.order_id}: {str(e)}", level='ERROR')
        
        # Redirect back to the order list
        if request.META.get('HTTP_REFERER'):
            return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        else:
            return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist')) 

def live_orders_view(request):
    from django.template.response import TemplateResponse
    from django.contrib import messages
    
    context = dict(
        admin.site.each_context(request),
        title="Live Orders from IB Gateway",
    )
    
    # Only process if user requested refresh
    if request.method == 'POST' and request.POST.get('action') == 'refresh':
        orders = []
        executions = []
        
        try:
            # Get the active configuration
            config = IBConfig.objects.filter(is_active=True).first()
            if not config:
                messages.error(request, "No active IB Gateway configuration found")
                return TemplateResponse(request, "admin/ib_gateway/live_orders.html", context)
                
            # Connect to IB Gateway
            ib = IBConnection(config.host, config.port, config.client_id)
            if not ib.connect():
                messages.error(request, "Failed to connect to IB Gateway")
                return TemplateResponse(request, "admin/ib_gateway/live_orders.html", context)
                
            try:
                # Set up the wrapper to handle opened orders
                orders_received = []
                executions_received = []
                
                # Store the original methods
                original_openOrder = ib.api.openOrder
                original_openOrderEnd = ib.api.openOrderEnd
                original_execDetails = ib.api.execDetails
                
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
                
                # Replace the methods
                ib.api.openOrder = handle_open_order
                ib.api.openOrderEnd = handle_open_order_end
                ib.api.execDetails = handle_exec_details
                
                # Request open orders
                logger.info("Requesting open orders from IB Gateway...")
                ib.api.reqOpenOrders()
                
                # Wait for data to be received
                time.sleep(3)
                
                # Request executions
                from ibapi.execution import ExecutionFilter
                exec_filter = ExecutionFilter()
                exec_filter.clientId = config.client_id
                exec_filter.time = ""  # Empty string gets all executions
                
                # Request executions
                ib.api.reqExecutions(1, exec_filter)
                
                # Wait for data to be received
                time.sleep(3)
                
                # Process results
                orders = orders_received
                executions = executions_received
                
                # Update context with results
                if orders:
                    messages.success(request, f"Found {len(orders)} open orders in IB Gateway")
                else:
                    messages.warning(request, "No open orders found in IB Gateway")
                    
                if executions:
                    messages.success(request, f"Found {len(executions)} executions in IB Gateway")
                    
            finally:
                # Always disconnect from IB Gateway
                ib.disconnect()
                
        except Exception as e:
            logger.error(f"Error fetching orders from IB Gateway: {str(e)}")
            messages.error(request, f"Error fetching orders from IB Gateway: {str(e)}")
        
        # Add results to context
        context.update({
            'orders': orders,
            'executions': executions,
            'refresh_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        })
        
    return TemplateResponse(request, "admin/ib_gateway/live_orders.html", context)

# Register the custom view by adding the URLs directly
original_get_urls = admin.AdminSite.get_urls

def get_urls(self):
    urls = original_get_urls(self)
    from django.urls import path
    # Add the live orders view URL
    urls.append(
        path('ib_gateway/live-orders/', 
             self.admin_view(live_orders_view), 
             name="ib_gateway_live_orders")
    )
    # Add the fetch all orders URL
    urls.append(
        path('ib_gateway/fetch-all-orders/',
             self.admin_view(fetch_all_orders_view),
             name="fetch_all_orders")
    )
    return urls

# Monkey patch the AdminSite.get_urls method
admin.AdminSite.get_urls = get_urls

# Add a standalone view for fetching all orders
def fetch_all_orders_view(request):
    from django.contrib import messages
    
    if request.method == 'POST':
        # Create an instance of the OrderAdmin
        model_admin = OrderAdmin(Order, admin.site)
        # Call the fetch_all_orders_from_ib method with an empty queryset
        model_admin.fetch_all_orders_from_ib(request, Order.objects.none())
        
    # Redirect back to the order changelist
    return HttpResponseRedirect(reverse('admin:ib_gateway_order_changelist')) 