# Generated by Django 5.0.2 on 2025-05-12 14:38

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('broker', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='IBConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(default='127.0.0.1', help_text='IB Gateway host address', max_length=255)),
                ('port', models.IntegerField(default=4002, help_text='IB Gateway port (4001 for live, 4002 for paper)')),
                ('client_id', models.IntegerField(default=1, help_text='Client ID for connection')),
                ('is_active', models.BooleanField(default=True, help_text='Whether this configuration is active')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'IB Gateway Configuration',
                'verbose_name_plural': 'IB Gateway Configurations',
            },
        ),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_id', models.CharField(help_text='IB Order ID', max_length=50, unique=True)),
                ('action', models.CharField(choices=[('BUY', 'Buy'), ('SELL', 'Sell')], help_text='Buy or Sell', max_length=10)),
                ('symbol', models.CharField(help_text='Ticker symbol', max_length=20)),
                ('sec_type', models.CharField(default='STK', help_text='Security type (STK, OPT, FUT, CASH)', max_length=10)),
                ('exchange', models.CharField(default='SMART', help_text='Exchange', max_length=20)),
                ('currency', models.CharField(default='USD', help_text='Currency', max_length=3)),
                ('quantity', models.DecimalField(decimal_places=5, help_text='Order quantity', max_digits=15)),
                ('order_type', models.CharField(choices=[('MKT', 'Market'), ('LMT', 'Limit'), ('STP', 'Stop'), ('STP_LMT', 'Stop Limit')], default='MKT', help_text='Order type', max_length=10)),
                ('limit_price', models.DecimalField(blank=True, decimal_places=5, help_text='Limit price if applicable', max_digits=15, null=True)),
                ('stop_price', models.DecimalField(blank=True, decimal_places=5, help_text='Stop price if applicable', max_digits=15, null=True)),
                ('status', models.CharField(choices=[('SUBMITTED', 'Submitted'), ('ACCEPTED', 'Accepted'), ('FILLED', 'Filled'), ('CANCELLED', 'Cancelled'), ('REJECTED', 'Rejected'), ('PENDING', 'Pending')], default='PENDING', help_text='Order status', max_length=20)),
                ('filled_quantity', models.DecimalField(decimal_places=5, default=0, help_text='Quantity filled', max_digits=15)),
                ('avg_fill_price', models.DecimalField(blank=True, decimal_places=5, help_text='Average fill price', max_digits=15, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('webhook', models.ForeignKey(blank=True, help_text='Related webhook that triggered this order', null=True, on_delete=django.db.models.deletion.SET_NULL, to='broker.webhook')),
            ],
            options={
                'verbose_name': 'IB Order',
                'verbose_name_plural': 'IB Orders',
                'ordering': ['-created_at'],
            },
        ),
    ]
