# app/curriculum/rate_limiter.py

import logging
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, Tuple

from flask import jsonify, request
from flask_login import current_user

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter implementation"""

    def __init__(self):
        self.requests = {}  # {key: [(timestamp, count), ...]}
        self.blocked = {}  # {key: unblock_timestamp}

    def is_allowed(self, key: str, limit: int, window: int) -> Tuple[bool, Dict]:
        """
        Check if request is allowed
        
        Args:
            key: Unique identifier for the client
            limit: Maximum requests per window
            window: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, info_dict)
        """
        now = time.time()

        # Check if currently blocked
        if key in self.blocked:
            if now < self.blocked[key]:
                return False, {
                    'blocked_until': self.blocked[key],
                    'retry_after': int(self.blocked[key] - now)
                }
            else:
                # Unblock
                del self.blocked[key]

        # Clean old requests
        if key in self.requests:
            self.requests[key] = [
                (ts, count) for ts, count in self.requests[key]
                if now - ts < window
            ]

        # Count current requests in window
        current_requests = sum(
            count for ts, count in self.requests.get(key, [])
        )

        if current_requests >= limit:
            # Block for remaining window time
            oldest_request = min(self.requests[key], key=lambda x: x[0])[0]
            block_until = oldest_request + window
            self.blocked[key] = block_until

            return False, {
                'limit': limit,
                'window': window,
                'current_requests': current_requests,
                'blocked_until': block_until,
                'retry_after': int(block_until - now)
            }

        # Allow request and record it
        if key not in self.requests:
            self.requests[key] = []

        self.requests[key].append((now, 1))

        return True, {
            'limit': limit,
            'window': window,
            'current_requests': current_requests + 1,
            'remaining': limit - current_requests - 1
        }

    def get_status(self, key: str, limit: int, window: int) -> Dict:
        """Get current rate limit status for key"""
        now = time.time()

        # Check if blocked
        if key in self.blocked and now < self.blocked[key]:
            return {
                'blocked': True,
                'blocked_until': self.blocked[key],
                'retry_after': int(self.blocked[key] - now)
            }

        # Count current requests
        current_requests = sum(
            count for ts, count in self.requests.get(key, [])
            if now - ts < window
        )

        return {
            'blocked': False,
            'limit': limit,
            'window': window,
            'current_requests': current_requests,
            'remaining': max(0, limit - current_requests)
        }


# Global rate limiter instance
rate_limiter = RateLimiter()


def get_client_key() -> str:
    """Get unique client identifier"""
    if current_user.is_authenticated:
        return f"user_{current_user.id}"
    else:
        # Use IP address for anonymous users
        return f"ip_{request.remote_addr}"


def rate_limit(limit: int = 60, window: int = 60, per: str = 'user'):
    """
    Rate limiting decorator
    
    Args:
        limit: Maximum requests per window
        window: Time window in seconds
        per: Rate limiting scope ('user', 'ip', 'endpoint')
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate rate limit key
            key_parts = []

            if per == 'user':
                key_parts.append(get_client_key())
            elif per == 'ip':
                key_parts.append(f"ip_{request.remote_addr}")
            elif per == 'endpoint':
                key_parts.extend([get_client_key(), request.endpoint])

            key = ':'.join(key_parts)

            # Check rate limit
            allowed, info = rate_limiter.is_allowed(key, limit, window)

            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for {key}: {info.get('current_requests', 0)}/{limit}"
                )

                response = jsonify({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests. Limit: {limit} per {window} seconds',
                    'retry_after': info.get('retry_after', window)
                })
                response.status_code = 429
                response.headers['X-RateLimit-Limit'] = str(limit)
                response.headers['X-RateLimit-Window'] = str(window)
                response.headers['X-RateLimit-Remaining'] = '0'
                response.headers['X-RateLimit-Reset'] = str(int(info.get('blocked_until', time.time() + window)))
                response.headers['Retry-After'] = str(info.get('retry_after', window))

                return response

            # Add rate limit headers to response
            try:
                result = f(*args, **kwargs)

                # Add headers if it's a Flask response
                if hasattr(result, 'headers'):
                    result.headers['X-RateLimit-Limit'] = str(limit)
                    result.headers['X-RateLimit-Window'] = str(window)
                    result.headers['X-RateLimit-Remaining'] = str(info.get('remaining', 0))
                    result.headers['X-RateLimit-Reset'] = str(int(time.time() + window))

                return result

            except Exception as e:
                # Don't count failed requests against rate limit
                logger.error(f"Error in rate-limited function {f.__name__}: {str(e)}")
                raise

        return decorated_function

    return decorator


class CurriculumRateLimits:
    """Rate limits specific to curriculum endpoints"""

    # General API limits
    API_GENERAL = {'limit': 100, 'window': 60}  # 100 requests per minute

    # Lesson interaction limits
    LESSON_SUBMIT = {'limit': 30, 'window': 60}  # 30 submissions per minute
    LESSON_ACCESS = {'limit': 50, 'window': 60}  # 50 lesson views per minute

    # Progress updates
    PROGRESS_UPDATE = {'limit': 20, 'window': 60}  # 20 progress updates per minute

    # SRS/Card reviews
    CARD_REVIEW = {'limit': 200, 'window': 60}  # 200 card reviews per minute

    # Admin operations
    ADMIN_GENERAL = {'limit': 200, 'window': 60}  # 200 admin requests per minute
    ADMIN_MODIFY = {'limit': 50, 'window': 60}  # 50 modifications per minute

    # Import operations
    IMPORT_CURRICULUM = {'limit': 5, 'window': 300}  # 5 imports per 5 minutes


def curriculum_rate_limit(limit_type: str):
    """Apply curriculum-specific rate limits"""
    limits = getattr(CurriculumRateLimits, limit_type, CurriculumRateLimits.API_GENERAL)
    return rate_limit(limit=limits['limit'], window=limits['window'], per='user')


def adaptive_rate_limit(base_limit: int = 60, window: int = 60):
    """
    Adaptive rate limiting based on user behavior
    
    Args:
        base_limit: Base limit for normal users
        window: Time window in seconds
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Adjust limits based on user type and behavior
            limit = base_limit

            if current_user.is_authenticated:
                # Premium users get higher limits
                if hasattr(current_user, 'is_premium') and current_user.is_premium:
                    limit = int(base_limit * 1.5)

                # Admins get much higher limits
                if current_user.is_admin:
                    limit = int(base_limit * 5)

                # Long-time users get slightly higher limits
                if hasattr(current_user, 'created_at'):
                    account_age = datetime.utcnow() - current_user.created_at
                    if account_age > timedelta(days=30):
                        limit = int(limit * 1.2)

            # Apply rate limiting with adjusted limit
            return rate_limit(limit=limit, window=window, per='user')(f)(*args, **kwargs)

        return decorated_function

    return decorator


class RateLimitMiddleware:
    """Middleware for global rate limiting"""

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize middleware with Flask app"""
        app.before_request(self.before_request)

    def before_request(self):
        """Check global rate limits before each request"""
        # Apply global rate limits to curriculum endpoints
        if request.endpoint and request.endpoint.startswith('curriculum.'):
            # Different limits for different endpoint types
            if request.endpoint.startswith('curriculum.api'):
                # API endpoints get stricter limits
                allowed, info = rate_limiter.is_allowed(
                    get_client_key(),
                    100,  # 100 requests per minute
                    60
                )
            else:
                # Regular endpoints get more lenient limits
                allowed, info = rate_limiter.is_allowed(
                    get_client_key(),
                    200,  # 200 requests per minute
                    60
                )

            if not allowed:
                logger.warning(f"Global rate limit exceeded for {get_client_key()}")
                response = jsonify({
                    'error': 'Too many requests',
                    'message': 'Please slow down your requests',
                    'retry_after': info.get('retry_after', 60)
                })
                response.status_code = 429
                return response


def init_rate_limiting(app):
    """Initialize rate limiting for the application"""
    middleware = RateLimitMiddleware(app)

    # Add rate limit status endpoint
    @app.route('/curriculum/rate-limit-status')
    def rate_limit_status():
        """Get current rate limit status"""
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        key = get_client_key()

        # Get status for different limit types
        status = {
            'general_api': rate_limiter.get_status(key, 100, 60),
            'lesson_submit': rate_limiter.get_status(key, 30, 60),
            'progress_update': rate_limiter.get_status(key, 20, 60),
            'card_review': rate_limiter.get_status(key, 200, 60)
        }

        return jsonify(status)


class BurstProtection:
    """Protection against burst attacks"""

    def __init__(self):
        self.burst_detection = {}  # {key: [timestamps]}
        self.burst_blocked = {}  # {key: block_until}

    def check_burst(self, key: str, threshold: int = 10, window: int = 5) -> bool:
        """
        Check for burst attacks
        
        Args:
            key: Client identifier
            threshold: Max requests in burst window
            window: Burst detection window in seconds
            
        Returns:
            True if burst detected
        """
        now = time.time()

        # Check if currently blocked for burst
        if key in self.burst_blocked:
            if now < self.burst_blocked[key]:
                return True
            else:
                del self.burst_blocked[key]

        # Clean old requests
        if key in self.burst_detection:
            self.burst_detection[key] = [
                ts for ts in self.burst_detection[key]
                if now - ts < window
            ]

        # Add current request
        if key not in self.burst_detection:
            self.burst_detection[key] = []

        self.burst_detection[key].append(now)

        # Check for burst
        if len(self.burst_detection[key]) > threshold:
            # Block for 5 minutes
            self.burst_blocked[key] = now + 300
            logger.warning(f"Burst attack detected for {key}")
            return True

        return False


# Global burst protection
burst_protection = BurstProtection()


def protect_against_burst(threshold: int = 10, window: int = 5):
    """Decorator to protect against burst attacks"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            key = get_client_key()

            if burst_protection.check_burst(key, threshold, window):
                logger.warning(f"Burst attack blocked for {key}")
                return jsonify({
                    'error': 'Burst attack detected',
                    'message': 'Too many requests in short time. Please wait.'
                }), 429

            return f(*args, **kwargs)

        return decorated_function

    return decorator
