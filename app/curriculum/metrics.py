# app/curriculum/metrics.py

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import g, request
from flask_login import current_user

from app.utils.db import db

logger = logging.getLogger(__name__)


@dataclass
class RequestMetric:
    """Single request metric data"""
    timestamp: datetime
    endpoint: str
    method: str
    response_time: float
    status_code: int
    user_id: Optional[int]
    ip_address: str
    user_agent: str
    queries_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


@dataclass
class DatabaseMetric:
    """Database query metric"""
    timestamp: datetime
    query_type: str
    duration: float
    table_name: str
    rows_returned: int


@dataclass
class UserActivityMetric:
    """User activity metric"""
    timestamp: datetime
    user_id: int
    activity_type: str
    lesson_id: Optional[int]
    module_id: Optional[int]
    level_id: Optional[int]
    session_duration: Optional[float]


class MetricsCollector:
    """Centralized metrics collection system"""

    def __init__(self, max_history: int = 10000):
        self.max_history = max_history

        # Request metrics
        self.request_metrics = deque(maxlen=max_history)
        self.requests_per_endpoint = defaultdict(int)
        self.response_times = defaultdict(list)
        self.error_count = defaultdict(int)

        # Database metrics
        self.database_metrics = deque(maxlen=max_history)
        self.slow_queries = deque(maxlen=100)
        self.queries_per_table = defaultdict(int)

        # User activity metrics
        self.user_activity = deque(maxlen=max_history)
        self.active_users = set()
        self.lesson_access_count = defaultdict(int)

        # Cache metrics
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_operations = defaultdict(int)

        # Performance indicators
        self.start_time = datetime.now(timezone.utc)
        self.peak_concurrent_users = 0

    def record_request(self, metric: RequestMetric):
        """Record a request metric"""
        self.request_metrics.append(metric)
        self.requests_per_endpoint[metric.endpoint] += 1

        # Track response times
        if len(self.response_times[metric.endpoint]) >= 100:
            self.response_times[metric.endpoint].pop(0)
        self.response_times[metric.endpoint].append(metric.response_time)

        # Track errors
        if metric.status_code >= 400:
            self.error_count[metric.endpoint] += 1

        # Track active users
        if metric.user_id:
            self.active_users.add(metric.user_id)

            # Clean old active users (remove after 30 minutes of inactivity)
            self._clean_active_users()

    def record_database_query(self, metric: DatabaseMetric):
        """Record a database query metric"""
        self.database_metrics.append(metric)
        self.queries_per_table[metric.table_name] += 1

        # Track slow queries
        if metric.duration > 0.1:  # Slow query threshold
            self.slow_queries.append(metric)

    def record_user_activity(self, metric: UserActivityMetric):
        """Record user activity metric"""
        self.user_activity.append(metric)

        if metric.lesson_id:
            self.lesson_access_count[metric.lesson_id] += 1

    def record_cache_operation(self, operation: str, hit: bool = None):
        """Record cache operation"""
        self.cache_operations[operation] += 1

        if hit is True:
            self.cache_hits += 1
        elif hit is False:
            self.cache_misses += 1

    def _clean_active_users(self):
        """Remove inactive users from active set"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        # Find recent user activity
        recent_users = set()
        for metric in reversed(self.request_metrics):
            if metric.timestamp < cutoff_time:
                break
            if metric.user_id:
                recent_users.add(metric.user_id)

        self.active_users = recent_users

        # Update peak concurrent users
        if len(self.active_users) > self.peak_concurrent_users:
            self.peak_concurrent_users = len(self.active_users)

    def get_summary_stats(self, hours: int = 1) -> Dict[str, Any]:
        """Get summary statistics for the last N hours"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Filter recent metrics
        recent_requests = [
            m for m in self.request_metrics
            if m.timestamp >= cutoff_time
        ]

        recent_db_queries = [
            m for m in self.database_metrics
            if m.timestamp >= cutoff_time
        ]

        recent_activities = [
            m for m in self.user_activity
            if m.timestamp >= cutoff_time
        ]

        # Calculate statistics
        total_requests = len(recent_requests)
        successful_requests = len([r for r in recent_requests if r.status_code < 400])
        error_rate = ((total_requests - successful_requests) / total_requests * 100) if total_requests > 0 else 0

        response_times = [r.response_time for r in recent_requests]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        p95_response_time = sorted(response_times)[int(len(response_times) * 0.95)] if response_times else 0

        # Database stats
        total_queries = len(recent_db_queries)
        slow_queries_count = len([q for q in recent_db_queries if q.duration > 0.1])

        # User stats
        unique_users = len(set(r.user_id for r in recent_requests if r.user_id))

        return {
            'period': f'{hours} hours',
            'requests': {
                'total': total_requests,
                'successful': successful_requests,
                'error_rate': round(error_rate, 2),
                'avg_response_time': round(avg_response_time, 3),
                'p95_response_time': round(p95_response_time, 3)
            },
            'database': {
                'total_queries': total_queries,
                'slow_queries': slow_queries_count,
                'queries_per_request': round(total_queries / total_requests, 2) if total_requests > 0 else 0
            },
            'users': {
                'unique_users': unique_users,
                'active_users': len(self.active_users),
                'peak_concurrent': self.peak_concurrent_users,
                'activities': len(recent_activities)
            },
            'cache': {
                'hit_rate': round(self.cache_hits / (self.cache_hits + self.cache_misses) * 100, 2)
                if (self.cache_hits + self.cache_misses) > 0 else 0,
                'total_operations': sum(self.cache_operations.values())
            }
        }

    def get_endpoint_stats(self) -> List[Dict[str, Any]]:
        """Get statistics per endpoint"""
        endpoint_stats = []

        for endpoint in self.requests_per_endpoint:
            response_times = self.response_times.get(endpoint, [])
            errors = self.error_count.get(endpoint, 0)
            total_requests = self.requests_per_endpoint[endpoint]

            if response_times:
                avg_time = sum(response_times) / len(response_times)
                p95_time = sorted(response_times)[int(len(response_times) * 0.95)]
            else:
                avg_time = p95_time = 0

            endpoint_stats.append({
                'endpoint': endpoint,
                'total_requests': total_requests,
                'error_count': errors,
                'error_rate': round(errors / total_requests * 100, 2) if total_requests > 0 else 0,
                'avg_response_time': round(avg_time, 3),
                'p95_response_time': round(p95_time, 3)
            })

        return sorted(endpoint_stats, key=lambda x: x['total_requests'], reverse=True)

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database performance statistics"""
        if not self.database_metrics:
            return {}

        # Query distribution by table
        table_stats = []
        for table, count in self.queries_per_table.items():
            table_queries = [m for m in self.database_metrics if m.table_name == table]
            avg_duration = sum(q.duration for q in table_queries) / len(table_queries)

            table_stats.append({
                'table': table,
                'query_count': count,
                'avg_duration': round(avg_duration, 3),
                'slow_queries': len([q for q in table_queries if q.duration > 0.1])
            })

        # Recent slow queries
        recent_slow = list(self.slow_queries)[-10:]
        slow_query_details = [{
            'table': q.table_name,
            'duration': round(q.duration, 3),
            'timestamp': q.timestamp.isoformat()
        } for q in recent_slow]

        return {
            'total_queries': len(self.database_metrics),
            'slow_queries_count': len(self.slow_queries),
            'tables': sorted(table_stats, key=lambda x: x['query_count'], reverse=True),
            'recent_slow_queries': slow_query_details
        }

    def get_user_activity_stats(self) -> Dict[str, Any]:
        """Get user activity statistics"""
        if not self.user_activity:
            return {}

        # Activity distribution
        activity_types = defaultdict(int)
        for activity in self.user_activity:
            activity_types[activity.activity_type] += 1

        # Most accessed lessons
        top_lessons = sorted(
            self.lesson_access_count.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        # Session durations
        sessions_with_duration = [
            a.session_duration for a in self.user_activity
            if a.session_duration is not None
        ]

        avg_session_duration = (
            sum(sessions_with_duration) / len(sessions_with_duration)
            if sessions_with_duration else 0
        )

        return {
            'total_activities': len(self.user_activity),
            'activity_types': dict(activity_types),
            'top_lessons': [{'lesson_id': lid, 'access_count': count} for lid, count in top_lessons],
            'avg_session_duration': round(avg_session_duration, 2) if avg_session_duration else None,
            'unique_users_active': len(self.active_users)
        }


# Global metrics collector
metrics_collector = MetricsCollector()


def track_request_metrics(f):
    """Decorator to track request metrics"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        start_query_count = getattr(g, 'query_count', 0)

        try:
            result = f(*args, **kwargs)
            status_code = getattr(result, 'status_code', 200)

        except Exception as e:
            status_code = 500
            raise

        finally:
            response_time = time.time() - start_time
            queries_count = getattr(g, 'query_count', 0) - start_query_count

            metric = RequestMetric(
                timestamp=datetime.now(timezone.utc),
                endpoint=request.endpoint or 'unknown',
                method=request.method,
                response_time=response_time,
                status_code=status_code,
                user_id=current_user.id if current_user.is_authenticated else None,
                ip_address=request.remote_addr or '',
                user_agent=request.headers.get('User-Agent', ''),
                queries_count=queries_count
            )

            metrics_collector.record_request(metric)

        return result

    return decorated_function


def track_database_query(query_type: str, table_name: str, duration: float, rows_returned: int = 0):
    """Track a database query"""
    metric = DatabaseMetric(
        timestamp=datetime.now(timezone.utc),
        query_type=query_type,
        duration=duration,
        table_name=table_name,
        rows_returned=rows_returned
    )

    metrics_collector.record_database_query(metric)


def track_user_activity(activity_type: str, lesson_id: int = None, module_id: int = None,
                        level_id: int = None, session_duration: float = None):
    """Track user activity"""
    if not current_user.is_authenticated:
        return

    metric = UserActivityMetric(
        timestamp=datetime.now(timezone.utc),
        user_id=current_user.id,
        activity_type=activity_type,
        lesson_id=lesson_id,
        module_id=module_id,
        level_id=level_id,
        session_duration=session_duration
    )

    metrics_collector.record_user_activity(metric)


def track_cache_operation(operation: str, hit: bool = None):
    """Track cache operation"""
    metrics_collector.record_cache_operation(operation, hit)


class PerformanceProfiler:
    """Context manager for profiling code blocks"""

    def __init__(self, name: str, threshold: float = 0.1):
        self.name = name
        self.threshold = threshold
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time

        if duration > self.threshold:
            logger.warning(f"Slow operation '{self.name}': {duration:.3f}s")

        # You could also save this to metrics
        if exc_type is None:
            # Success
            logger.debug(f"Operation '{self.name}' completed in {duration:.3f}s")


def performance_profile(name: str = None, threshold: float = 0.1):
    """Decorator for profiling function performance"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            profile_name = name or f.__name__

            with PerformanceProfiler(profile_name, threshold):
                return f(*args, **kwargs)

        return decorated_function

    return decorator


class MetricsExporter:
    """Export metrics to external monitoring systems"""

    @staticmethod
    def export_to_prometheus() -> str:
        """Export metrics in Prometheus format"""
        stats = metrics_collector.get_summary_stats(1)

        prometheus_metrics = []

        # Request metrics
        prometheus_metrics.append(f"curriculum_requests_total {stats['requests']['total']}")
        prometheus_metrics.append(f"curriculum_request_duration_avg {stats['requests']['avg_response_time']}")
        prometheus_metrics.append(f"curriculum_request_duration_p95 {stats['requests']['p95_response_time']}")
        prometheus_metrics.append(f"curriculum_error_rate {stats['requests']['error_rate']}")

        # Database metrics
        prometheus_metrics.append(f"curriculum_db_queries_total {stats['database']['total_queries']}")
        prometheus_metrics.append(f"curriculum_db_slow_queries {stats['database']['slow_queries']}")

        # User metrics
        prometheus_metrics.append(f"curriculum_active_users {stats['users']['active_users']}")
        prometheus_metrics.append(f"curriculum_peak_users {stats['users']['peak_concurrent']}")

        # Cache metrics
        prometheus_metrics.append(f"curriculum_cache_hit_rate {stats['cache']['hit_rate']}")

        return '\n'.join(prometheus_metrics)

    @staticmethod
    def export_to_json() -> Dict[str, Any]:
        """Export comprehensive metrics as JSON"""
        return {
            'summary': metrics_collector.get_summary_stats(1),
            'endpoints': metrics_collector.get_endpoint_stats(),
            'database': metrics_collector.get_database_stats(),
            'user_activity': metrics_collector.get_user_activity_stats(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }


def init_metrics(app):
    """Initialize metrics collection for the application"""

    # Add metrics endpoints
    @app.route('/curriculum/metrics/summary')
    def metrics_summary():
        """Get metrics summary"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        hours = request.args.get('hours', 1, type=int)
        return metrics_collector.get_summary_stats(hours)

    @app.route('/curriculum/metrics/endpoints')
    def metrics_endpoints():
        """Get endpoint performance metrics"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        return {'endpoints': metrics_collector.get_endpoint_stats()}

    @app.route('/curriculum/metrics/database')
    def metrics_database():
        """Get database performance metrics"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        return metrics_collector.get_database_stats()

    @app.route('/curriculum/metrics/users')
    def metrics_users():
        """Get user activity metrics"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        return metrics_collector.get_user_activity_stats()

    @app.route('/curriculum/metrics/prometheus')
    def metrics_prometheus():
        """Get metrics in Prometheus format"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        return MetricsExporter.export_to_prometheus(), 200, {'Content-Type': 'text/plain'}

    @app.route('/curriculum/metrics/export')
    def metrics_export():
        """Export all metrics as JSON"""
        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        return MetricsExporter.export_to_json()

    logger.info("Initialized curriculum metrics collection")


# Database query monitoring hook
def setup_database_monitoring():
    """Setup database query monitoring"""

    def query_monitor(conn, cursor, statement, parameters, context, executemany):
        """Monitor database queries"""
        if hasattr(context, '_query_start_time'):
            duration = time.time() - context._query_start_time

            # Extract table name from query
            table_name = 'unknown'
            statement_lower = statement.lower().strip()

            if statement_lower.startswith('select'):
                # Extract table from SELECT statement
                from_index = statement_lower.find('from ')
                if from_index != -1:
                    table_part = statement_lower[from_index + 5:].split()[0]
                    table_name = table_part.strip('`"[]')
            elif statement_lower.startswith(('insert', 'update', 'delete')):
                # Extract table from INSERT/UPDATE/DELETE
                words = statement_lower.split()
                if len(words) > 2:
                    table_name = words[2].strip('`"[]')

            # Track query
            track_database_query(
                query_type=statement_lower.split()[0],
                table_name=table_name,
                duration=duration
            )

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """Before query execution"""
        context._query_start_time = time.time()

    # Register SQLAlchemy event listeners
    try:
        from flask import has_app_context
        if has_app_context():
            from sqlalchemy import event
            event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
            event.listen(db.engine, "after_cursor_execute", query_monitor)
            logger.info("Database query monitoring enabled")
        else:
            logger.warning("Cannot setup database monitoring: no app context")
    except Exception as e:
        logger.error(f"Failed to setup database monitoring: {str(e)}")


# Real-time metrics dashboard data
def get_real_time_dashboard_data() -> Dict[str, Any]:
    """Get real-time data for metrics dashboard"""
    now = datetime.now(timezone.utc)

    # Get metrics for different time windows
    last_5min = metrics_collector.get_summary_stats(hours=5 / 60)  # 5 minutes
    last_hour = metrics_collector.get_summary_stats(hours=1)
    last_day = metrics_collector.get_summary_stats(hours=24)

    # Current active metrics
    current_metrics = {
        'active_users': len(metrics_collector.active_users),
        'requests_per_minute': last_5min['requests']['total'] / 5,
        'error_rate': last_5min['requests']['error_rate'],
        'avg_response_time': last_5min['requests']['avg_response_time'],
        'cache_hit_rate': last_5min['cache']['hit_rate']
    }

    # Trending data
    trending = {
        'requests_trend': {
            '5min': last_5min['requests']['total'],
            '1hour': last_hour['requests']['total'],
            '24hour': last_day['requests']['total']
        },
        'response_time_trend': {
            '5min': last_5min['requests']['avg_response_time'],
            '1hour': last_hour['requests']['avg_response_time'],
            '24hour': last_day['requests']['avg_response_time']
        }
    }

    return {
        'current': current_metrics,
        'trending': trending,
        'top_endpoints': metrics_collector.get_endpoint_stats()[:5],
        'database_health': {
            'slow_queries': len(metrics_collector.slow_queries),
            'total_queries': len(metrics_collector.database_metrics)
        },
        'timestamp': now.isoformat()
    }
