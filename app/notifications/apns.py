"""Token-authenticated HTTP/2 APNs transport. Device tokens never enter logs."""
import time
from dataclasses import dataclass

import jwt
from flask import current_app


def configured():
    return all(current_app.config.get(key) for key in (
        'APNS_TEAM_ID', 'APNS_KEY_ID', 'APNS_PRIVATE_KEY', 'APNS_TOPIC'))


@dataclass(frozen=True)
class PushResult:
    accepted: bool
    invalid_device: bool = False


class APNsClient:
    def __enter__(self):
        import httpx
        config = current_app.config
        self.topic = config['APNS_TOPIC']
        self.bearer = jwt.encode(
            {'iss': config['APNS_TEAM_ID'], 'iat': int(time.time())},
            config['APNS_PRIVATE_KEY'].replace('\\n', '\n'), algorithm='ES256',
            headers={'kid': config['APNS_KEY_ID']})
        self.client = httpx.Client(http2=True, timeout=10, trust_env=False)
        return self

    def __exit__(self, *_):
        self.client.close()

    def send(self, device, *, title, body, collapse_id, expires_at, account_key, is_test=False):
        import httpx
        host = 'api.sandbox.push.apple.com' if device.environment == 'sandbox' else 'api.push.apple.com'
        try:
            reply = self.client.post(f'https://{host}/3/device/{device.token}', headers={
                'authorization': 'bearer ' + self.bearer,
                'apns-topic': self.topic,
                'apns-push-type': 'alert',
                'apns-priority': '10',
                'apns-expiration': str(expires_at),
                'apns-collapse-id': collapse_id,
            }, json={'aps': {'alert': {'title': title, 'body': body}, 'sound': 'default',
                            'thread-id': 'study-reminders'}, 'route': 'daily-plan',
                     'account': account_key, 'test': is_test})
        except httpx.HTTPError:
            # A timeout may already have been accepted by APNs. The durable
            # claim deliberately prevents resending that window.
            current_app.logger.warning('APNs transport failed; reminder window consumed')
            return PushResult(False)
        try:
            reason = reply.json().get('reason') if reply.status_code != 200 else None
        except (ValueError, AttributeError):
            reason = None
        invalid = reply.status_code == 410 or reason in ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered')
        if reply.status_code != 200:
            current_app.logger.warning('APNs rejected notification status=%s', reply.status_code)
        return PushResult(reply.status_code == 200, invalid)
