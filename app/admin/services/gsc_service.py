# app/admin/services/gsc_service.py

"""Google Search Console OAuth2 and data fetch service."""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

# Module-level imports guarded so the module loads even without google packages.
# Tests mock these names at app.admin.services.gsc_service.Flow / .Credentials / .build.
try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover
    Flow = None  # type: ignore[assignment,misc]
    Credentials = None  # type: ignore[assignment,misc]
    build = None  # type: ignore[assignment,misc]


def _require_libs() -> None:
    if Flow is None or Credentials is None or build is None:
        raise ImportError(
            'google-auth-oauthlib and google-api-python-client must be installed'
        )


def build_flow(redirect_uri: str, client_id: str, client_secret: str):
    """Return an OAuth2 Flow configured for the GSC read-only scope."""
    _require_libs()
    client_config = {
        'web': {
            'client_id': client_id,
            'client_secret': client_secret,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def get_verified_sites(credentials) -> list:
    """Return list of site URLs verified in Google Search Console."""
    _require_libs()
    service = build('webmasters', 'v3', credentials=credentials)
    resp = service.sites().list().execute()
    return [s['siteUrl'] for s in resp.get('siteEntry', [])]


def fetch_gsc_data(
    refresh_token: str,
    site_url: str,
    client_id: str,
    client_secret: str,
    days: int = 28,
) -> dict:
    """Fetch top-10 queries and daily time-series for the past *days* days.

    Returns:
        {
            queries: [{query, clicks, impressions, ctr, position}],
            total_clicks, total_impressions, avg_ctr, avg_position,
            chart_dates: [...], chart_clicks: [...], chart_impressions: [...]
        }
    """
    _require_libs()

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    service = build('webmasters', 'v3', credentials=creds)

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    date_range = {'startDate': start_date.isoformat(), 'endDate': end_date.isoformat()}

    # Top-10 queries
    query_resp = service.searchanalytics().query(
        siteUrl=site_url,
        body={**date_range, 'dimensions': ['query'], 'rowLimit': 10},
    ).execute()
    rows = query_resp.get('rows', [])
    queries = [
        {
            'query': r['keys'][0],
            'clicks': int(r.get('clicks', 0)),
            'impressions': int(r.get('impressions', 0)),
            'ctr': round(r.get('ctr', 0) * 100, 1),
            'position': round(r.get('position', 0), 1),
        }
        for r in rows
    ]

    # Daily time-series for 28-day chart. Per-date rows aggregate across ALL
    # queries, so sums over chart rows give site-wide totals (top-10 query
    # sums would under-report any site with >10 queries).
    date_resp = service.searchanalytics().query(
        siteUrl=site_url,
        body={**date_range, 'dimensions': ['date'], 'rowLimit': days + 5},
    ).execute()
    chart_rows = date_resp.get('rows', [])
    chart_dates = [r['keys'][0] for r in chart_rows]
    chart_clicks = [int(r.get('clicks', 0)) for r in chart_rows]
    chart_impressions = [int(r.get('impressions', 0)) for r in chart_rows]

    total_clicks = sum(chart_clicks)
    total_impressions = sum(chart_impressions)
    avg_ctr = round(total_clicks / total_impressions * 100, 1) if total_impressions else 0.0
    # Impression-weighted average position across the date series.
    weighted_position_sum = sum(
        float(r.get('position', 0)) * int(r.get('impressions', 0)) for r in chart_rows
    )
    avg_position = (
        round(weighted_position_sum / total_impressions, 1) if total_impressions else 0.0
    )

    return {
        'queries': queries,
        'total_clicks': total_clicks,
        'total_impressions': total_impressions,
        'avg_ctr': avg_ctr,
        'avg_position': avg_position,
        'chart_dates': chart_dates,
        'chart_clicks': chart_clicks,
        'chart_impressions': chart_impressions,
    }
