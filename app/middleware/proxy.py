"""Trust exactly the single configured reverse proxy in front of Gunicorn."""
from werkzeug.middleware.proxy_fix import ProxyFix


def apply_trusted_proxy(app):
    # nginx supplies Host itself and appends the trusted client IP to XFF.
    # An arbitrary X-Forwarded-Host must never control emailed URLs.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)
