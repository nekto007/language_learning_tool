"""
Flask-Caching configuration and utilities
"""
from flask_caching import Cache

# Initialize cache instance
cache = Cache(config={
    'CACHE_TYPE': 'SimpleCache',  # In-memory cache
    'CACHE_DEFAULT_TIMEOUT': 300  # 5 minutes default
})


def init_cache(app):
    """Initialize Flask-Caching with the app"""
    cache.init_app(app)
    return cache
