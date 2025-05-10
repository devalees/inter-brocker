from .settings import *

DEBUG = False

# Update this with your EC2 instance's public IP or domain
ALLOWED_HOSTS = [
    'ec2-16-170-148-120.eu-north-1.compute.amazonaws.com',
    '16.170.148.120'
]

# Security settings
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Static files
STATIC_ROOT = BASE_DIR / 'staticfiles' 