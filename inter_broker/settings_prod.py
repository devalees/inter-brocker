from .settings import *

DEBUG = False

# Update this with your EC2 instance's public IP or domain
ALLOWED_HOSTS = ['*']  # For testing. In production, specify your domain

# Security settings
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Static files
STATIC_ROOT = BASE_DIR / 'staticfiles' 