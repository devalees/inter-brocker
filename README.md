# Django Inter-Broker Application

A simple Django application for inter-broker communication.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Linux/Mac
# or
.\venv\Scripts\activate  # On Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Start the development server:
```bash
python manage.py runserver
```

The application will be available at http://127.0.0.1:8000/

## Webhook API Endpoint

The application provides a webhook endpoint to receive and store incoming webhook data.

### Development Environment
In development, the webhook endpoint is available at:
```
POST http://127.0.0.1:8000/api/webhook/
```

### Production Environment (EC2)
In production, the webhook endpoint will be available on standard ports:
```
POST http://your-ec2-ip/api/webhook/     # Port 80
POST https://your-ec2-ip/api/webhook/    # Port 443 (after SSL setup)
```

### Request Format
- Content-Type: application/json
- Method: POST
- Body: Any valid JSON payload

### Example Request (Development)
```bash
curl -X POST http://127.0.0.1:8000/api/webhook/ \
  -H "Content-Type: application/json" \
  -d '{
    "event": "test_event",
    "data": {
      "key": "value",
      "timestamp": "2024-05-10T12:00:00Z"
    }
  }'
```

### Example Request (Production)
```bash
curl -X POST http://your-ec2-ip/api/webhook/ \
  -H "Content-Type: application/json" \
  -d '{
    "event": "test_event",
    "data": {
      "key": "value",
      "timestamp": "2024-05-10T12:00:00Z"
    }
  }'
```

### Response
- Status: 201 Created (on success)
- Body: JSON containing the stored webhook data including:
  - ID
  - Payload
  - Headers
  - Source IP
  - Received timestamp

### Viewing Webhook Data
All received webhooks can be viewed in the Django admin interface at `/admin/broker/webhook/`

### Production Deployment
For production deployment on EC2:
1. The webhook endpoint will be available on standard ports (80/443)
2. Use the provided `deploy.sh` script for deployment
3. Configure your webhook provider to send requests to:
   - HTTP: `http://your-ec2-ip/api/webhook/` (Port 80)
   - HTTPS: `https://your-ec2-ip/api/webhook/` (Port 443, after SSL setup)
4. Nginx will handle the incoming requests on ports 80/443 and forward them to Django running internally on port 8000 