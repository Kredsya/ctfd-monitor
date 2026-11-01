import io
import time
import unittest
import urllib.error
from unittest.mock import Mock
from ctfd_monitor.client import ApiError, CTFdClient

class ClientTests(unittest.TestCase):
    def test_rate_limit_prevents_further_requests(self):
        client = CTFdClient('https://example.org', '', '')
        client.opener = Mock()
        client.opener.open.side_effect = urllib.error.HTTPError('https://example.org/api', 429, 'Too Many Requests', {'Retry-After': '120'}, io.BytesIO(b'[]'))
        for _ in range(2):
            with self.assertRaises(ApiError) as caught:
                client.request_json('/api')
            self.assertEqual(caught.exception.status, 429)
        self.assertEqual(client.opener.open.call_count, 1)
        self.assertGreater(client.retry_until, time.monotonic() + 110)

    def test_auth_failure_does_not_try_other_routes(self):
        client = CTFdClient('https://example.org', '', '')
        client.request_json = Mock(side_effect=ApiError('/v2', 401, 'Unauthorized'))
        with self.assertRaises(ApiError):
            client.request_json_routes(('/v2', '/v1'))
        client.request_json.assert_called_once_with('/v2')
