# app/curriculum/middleware.py

import logging
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict

from flask import current_app, flash, g, jsonify, redirect, request, url_for
from flask_login import current_user

logger = logging.getLogger(__name__)


class RequestMetrics:
    """Class to track request metrics"""

    def __init__(self):
        self.request_count = 0
        self.total_response_time = 0
        self.slow_requests = []
        self.error_count = 0

    def add_request(self, response_time: float, status_code: int, endpoint: str):
        """Add request metrics"""
        self.request_count += 1
        self.total_response_time += response_time

        if response_time > 1.0:  # Slow request threshold
            self.slow_requests.append({
                'endpoint': endpoint,
                'response_time': response_time,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

        if status_code >= 400:
            self.error_count += 1

    def get_average_response_time(self) -> float:
        """Get average response time"""
        if self.request_count == 0:
            return 0
        return self.total_response_time / self.request_count

    def get_slow_requests(self, limit: int = 10) -> list:
        """Get recent slow requests"""
        return self.slow_requests[-limit:]


# Global metrics instance
request_metrics = RequestMetrics()


def performance_monitor(f):
    """Decorator to monitor function performance"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()

        try:
            result = f(*args, **kwargs)
            execution_time = time.time() - start_time

            # Log slow functions
            if execution_time > 0.5:
                logger.warning(
                    f"Slow function execution: {f.__name__} took {execution_time:.3f}s"
                )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"Function {f.__name__} failed after {execution_time:.3f}s: {str(e)}"
            )
            raise

    return decorated_function


def track_curriculum_access(f):
    """Decorator to track curriculum access patterns"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated:
            # Log access patterns for analytics
            access_data = {
                'user_id': current_user.id,
                'endpoint': request.endpoint,
                'method': request.method,
                'timestamp': datetime.now(timezone.utc),
                'user_agent': request.headers.get('User-Agent', ''),
                'ip_address': request.remote_addr
            }

            # Store in database or send to analytics service
            try:
                log_user_access(access_data)
            except Exception as e:
                logger.error(f"Failed to log user access: {str(e)}")

        return f(*args, **kwargs)

    return decorated_function


def log_user_access(access_data: Dict[str, Any]):
    """Log user access to database"""
    try:
        # Create access log entry (you might want to create a separate table for this)
        from app.curriculum.models import LessonProgress

        # For now, we'll just log to application logs
        # In production, you might want to use a separate analytics service
        logger.info(
            f"User access: user_id={access_data['user_id']}, "
            f"endpoint={access_data['endpoint']}, "
            f"method={access_data['method']}"
        )

    except Exception as e:
        logger.error(f"Error logging user access: {str(e)}")


def curriculum_error_handler(f):
    """Enhanced error handler for curriculum routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"Validation error in {f.__name__}: {str(e)}")
            if request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Invalid input data',
                    'details': str(e) if current_app.debug else None
                }), 400
            else:
                flash('Неверные данные. Попробуйте еще раз.', 'error')
                return redirect(request.referrer or url_for('curriculum.index'))

        except PermissionError as e:
            logger.warning(f"Permission denied in {f.__name__}: {str(e)}")
            if request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Access denied'
                }), 403
            else:
                flash('У вас нет прав для выполнения этого действия.', 'error')
                return redirect(url_for('curriculum.index'))

        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}: {str(e)}", exc_info=True)
            if request.is_json:
                return jsonify({
                    'success': False,
                    'error': 'Internal server error',
                    'details': str(e) if current_app.debug else None
                }), 500
            else:
                flash('Произошла внутренняя ошибка. Попробуйте позже.', 'error')
                return redirect(url_for('curriculum.index'))

    return decorated_function


class CurriculumMiddleware:
    """Middleware class for curriculum module"""

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize middleware with Flask app"""
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.teardown_appcontext(self.teardown)

    def before_request(self):
        """Called before each request"""
        g.start_time = time.time()

        # Log request for curriculum routes
        if request.endpoint and request.endpoint.startswith('curriculum.'):
            logger.info(
                f"Curriculum request: {request.method} {request.path} "
                f"from {request.remote_addr}"
            )

            # Track user activity
            if current_user.is_authenticated:
                g.user_id = current_user.id

    def after_request(self, response):
        """Called after each request"""
        if hasattr(g, 'start_time'):
            response_time = time.time() - g.start_time

            # Track metrics for curriculum routes
            if request.endpoint and request.endpoint.startswith('curriculum.'):
                request_metrics.add_request(
                    response_time=response_time,
                    status_code=response.status_code,
                    endpoint=request.endpoint
                )

                # Log slow requests
                if response_time > 1.0:
                    logger.warning(
                        f"Slow curriculum request: {request.endpoint} "
                        f"took {response_time:.3f}s"
                    )

                # Log errors
                if response.status_code >= 400:
                    logger.error(
                        f"Curriculum error: {request.endpoint} "
                        f"returned {response.status_code}"
                    )

        return response

    def teardown(self, exception):
        """Called when request context is torn down"""
        if exception:
            logger.error(f"Request ended with exception: {str(exception)}")


def init_curriculum_monitoring(app):
    """Initialize curriculum monitoring"""
    middleware = CurriculumMiddleware(app)

    # Add metrics endpoint
    @app.route('/curriculum/metrics')
    @require_admin
    def curriculum_metrics():
        """Get curriculum performance metrics"""
        return jsonify({
            'request_count': request_metrics.request_count,
            'average_response_time': request_metrics.get_average_response_time(),
            'error_count': request_metrics.error_count,
            'slow_requests': request_metrics.get_slow_requests(),
            'error_rate': (request_metrics.error_count / request_metrics.request_count * 100)
            if request_metrics.request_count > 0 else 0
        })


def require_admin(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)

    return decorated_function


class DatabaseQueryMonitor:
    """Monitor database queries for performance"""

    def __init__(self):
        self.query_count = 0
        self.slow_queries = []

    def log_query(self, query: str, duration: float):
        """Log database query"""
        self.query_count += 1

        if duration > 0.1:  # Slow query threshold
            self.slow_queries.append({
                'query': query[:200] + '...' if len(query) > 200 else query,
                'duration': duration,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

            logger.warning(f"Slow query ({duration:.3f}s): {query[:100]}...")

    def get_metrics(self) -> Dict[str, Any]:
        """Get query metrics"""
        return {
            'total_queries': self.query_count,
            'slow_queries_count': len(self.slow_queries),
            'recent_slow_queries': self.slow_queries[-10:]
        }


# Global query monitor
query_monitor = DatabaseQueryMonitor()


def monitor_db_queries(f):
    """Decorator to monitor database queries"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        initial_query_count = query_monitor.query_count

        try:
            result = f(*args, **kwargs)

            execution_time = time.time() - start_time
            queries_executed = query_monitor.query_count - initial_query_count

            if execution_time > 0.5 or queries_executed > 10:
                logger.warning(
                    f"Function {f.__name__}: {execution_time:.3f}s, "
                    f"{queries_executed} queries"
                )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"Function {f.__name__} failed after {execution_time:.3f}s: {str(e)}"
            )
            raise

    return decorated_function
