#!/bin/bash

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y python3-pip python3-venv nginx

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Collect static files
python3 manage.py collectstatic --noinput

# Copy Nginx configuration
sudo cp nginx.conf /etc/nginx/sites-available/inter_broker
sudo ln -s /etc/nginx/sites-available/inter_broker /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# Create systemd service
sudo tee /etc/systemd/system/inter_broker.service << EOF
[Unit]
Description=Inter Broker Gunicorn Service
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/mhd_interactive
Environment="PATH=/home/ubuntu/mhd_interactive/venv/bin"
ExecStart=/home/ubuntu/mhd_interactive/venv/bin/gunicorn -c gunicorn_config.py inter_broker.wsgi:application

[Install]
WantedBy=multi-user.target
EOF

# Start and enable service
sudo systemctl start inter_broker
sudo systemctl enable inter_broker 