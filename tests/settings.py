"""
This file contains django settings to run tests with runtests.py
"""
SECRET_KEY = 'fake-key'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'test',
        'USER': 'test',
        'PASSWORD': 'test',
        'HOST': '127.0.0.1',
        'PORT': '5432'
    }
}

LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django-clickhouse': {
            'handlers': ['console'],
            'level': 'DEBUG'
        }
    }
}

INSTALLED_APPS = [
    "src",
    "tests"
]

CLICKHOUSE_DATABASES = {
    'default': {
        'db_name': 'test',
        'username': 'default',
        'password': ''
    }
}

CLICKHOUSE_SYNC_BATCH_SIZE = 5000

CLICKHOUSE_REDIS_CONFIG = {
    'host': '127.0.0.1',
    'port': 6379,
    'db': 8,
    'socket_timeout': 10
}
