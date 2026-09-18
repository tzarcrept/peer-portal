"""WSGI config for the PEER portal."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'peer_portal.settings')

application = get_wsgi_application()
