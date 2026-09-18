"""
Django settings for the PEER portal (Project Execution and Evaluation Report).

A dashboard + operations portal for tracking capital/maintenance projects:
scope, prerequisites, regulatory approvals, schedule events and equipment,
with progress analytics (S-curves) and an AI insights layer on top.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: this key is fine for local/demo use on your own machine.
# For any real deployment, set the PEER_SECRET_KEY environment variable instead.
SECRET_KEY = os.environ.get(
    'PEER_SECRET_KEY',
    'django-insecure-peer-portal-demo-key-set-PEER_SECRET_KEY-before-deploying',
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('PEER_DEBUG', '1') == '1'

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'portal',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'peer_portal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'peer_portal.wsgi.application'

# Database -- all portal content lives here, via portal/models.py.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JS). 'portal' is a registered app, so Django finds
# portal/static/portal/... automatically -- no STATICFILES_DIRS needed.
STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ==================== AI Insights configuration ====================
# The insights feature is designed to degrade gracefully: every number shown in
# the dashboard is computed deterministically in portal/analytics.py. The AI layer
# only writes narrative on top of those already-computed facts. If the model is
# unreachable, or the call fails or times out, the portal falls back to a
# rule-based narrative generated from the exact same facts -- so the page always
# renders.
#
# THE MODEL RUNS LOCALLY. This is wired to Ollama on 127.0.0.1, not to any hosted
# API. Project schedules, budgets, contractor names and personnel never leave the
# machine the portal is running on. That is a deliberate constraint rather than a
# convenience: a project-controls tool holding a plant operator's live capital
# project data cannot post that data to a third-party endpoint, so a design that
# depends on a hosted model is not deployable in the environment this tool is for.
#
# Setup (one time):
#     1. Install Ollama from https://ollama.com/download
#     2. Pull a small instruct model:   ollama pull llama3.2
#     3. Ollama serves on 127.0.0.1:11434 automatically; nothing else to configure.
#
# If Ollama is not installed or not running, the connection is refused immediately
# (no hang, no timeout wait) and the portal uses the rule-based narrative instead.
AI_ENABLED = os.environ.get('PEER_AI_ENABLED', '1') == '1'
AI_MODEL = os.environ.get('PEER_AI_MODEL', 'llama3.2')
AI_API_URL = os.environ.get('PEER_AI_API_URL', 'http://127.0.0.1:11434/api/chat')
# Local inference on CPU is slower than a hosted API, so this is generous. The
# insight is cached afterwards (AI_CACHE_SECONDS) so the wait is paid once.
AI_TIMEOUT_SECONDS = float(os.environ.get('PEER_AI_TIMEOUT', '90'))
AI_MAX_TOKENS = int(os.environ.get('PEER_AI_MAX_TOKENS', '1200'))
# Cache AI narratives for this many seconds so repeated page loads don't re-run
# local inference. Set to 0 to disable caching.
AI_CACHE_SECONDS = int(os.environ.get('PEER_AI_CACHE_SECONDS', '900'))
