"""Timing contracts for stock CTFd and competition-specific config APIs."""
import json
import time
from datetime import datetime, timezone
from unittest.mock import patch
from ctfd_monitor.client import normalize_contest_end
from scenarios import Scenario, m


class ContestTimeTests(Scenario):
    def page(self, end):
        # Stock core template uses single-quoted keys and JSON values.
        body = "<script>window.init = {'userName': \"fake 'end': 1\", 'start': 1, 'end': " + json.dumps(end) + ", 'themeSettings': {},};</script>"
        self.routes['/login'] = (200, body.encode(), {'Content-Type':'text/html'})

    def test_stock_token_only_and_updated_or_removed_deadline(self):
        for value in (1893456000, 1893459600, None, 0, '0'):
            with self.subTest(value=value):
                self.page(value)
                self.monitor.refresh_contest_config(force=True)
                view = self.monitor.state.view()
                self.assertEqual(view['contest_end'], normalize_contest_end(value))
                self.assertTrue(view['contest_end_known'])
                if value in (None, 0, '0'):
                    self.assertEqual(m.competition_countdown(view)[0], 'NO LIMIT')
        self.assertTrue(all('Authorization' not in headers for path,headers in self.requests if path == '/login'))
        self.assertFalse(self.monitor.client.logged_in)

    def test_v2_iso_timezone_epoch_and_unlimited(self):
        for value in ('2030-01-01T09:00:00+09:00', '2030-01-01T00:00:00Z', 1893456000, '1893456000', None):
            with self.subTest(value=value):
                self.requests.clear()
                self.ok('/api/v2/config/', {'competition':{'end':value}})
                self.monitor.refresh_contest_config(force=True)
                self.assertEqual(self.monitor.state.contest_end, '' if value is None else '2030-01-01T00:00:00+00:00')
                self.assertEqual([p for p,_ in self.requests], ['/api/v2/config/'])

    def test_override_never_requests_server_and_poll_interval_refreshes(self):
        with patch.object(m,'CONTEST_END','2031-01-01T00:00:00Z'):
            self.monitor.refresh_contest_config(force=True)
            self.assertEqual(self.monitor.state.contest_end,m.CONTEST_END)
            self.assertEqual(self.requests,[])
        self.page(1893456000)
        self.monitor.refresh_contest_config(force=True)
        self.requests.clear(); self.page(1893459600)
        self.monitor.refresh_contest_config()
        self.assertEqual(self.requests,[])
        self.monitor.last_config_refresh -= m.CONFIG_POLL_INTERVAL
        self.monitor.refresh_contest_config()
        self.assertEqual(self.monitor.state.contest_end,'2030-01-01T01:00:00+00:00')

    def test_failures_do_not_erase_known_time_or_bypass_retry(self):
        self.page(1893456000); self.monitor.refresh_contest_config(force=True)
        saved=self.monitor.state.contest_end
        for status in (401,403,429,500,503):
            with self.subTest(status=status):
                self.monitor.client.retry_until=0;self.requests.clear()
                self.routes['/api/v2/config/']=(status,{}, {'Retry-After':'90'})
                self.monitor.refresh_contest_config(force=True)
                self.assertEqual(self.monitor.state.contest_end,saved)
                self.assertEqual([p for p,_ in self.requests],['/api/v2/config/'])
                if status==429:
                    self.requests.clear();self.monitor.refresh_contest_config(force=True)
                    self.assertEqual(self.requests,[])
        self.monitor.client.retry_until=0
        self.routes.pop('/api/v2/config/')
        self.routes['/login']=(429,b'',{'Retry-After':'120'})
        self.monitor.refresh_contest_config(force=True)
        self.assertGreater(self.monitor.client.retry_until,time.monotonic()+110)
        self.assertEqual(self.monitor.state.contest_end,saved)

    def test_missing_malformed_nested_and_nonfinite_data_keep_last_deadline(self):
        self.page(1893456000);self.monitor.refresh_contest_config(force=True)
        saved=self.monitor.state.contest_end
        for value in (True,False,{},[], 'garbage','2030-01-01T00:00:00',float('nan'),float('inf'),10**30):
            with self.subTest(value=value):
                self.page(value);self.monitor.refresh_contest_config(force=True)
                self.assertEqual(self.monitor.state.contest_end,saved)
        for body in (b'<html>no timing</html>', b"<script>window.init={'themeSettings':{'end':1}};</script>", b"<script>window.init={'end':alert(1)};</script>"):
            self.routes['/login']=(200,body,{})
            self.monitor.refresh_contest_config(force=True)
            self.assertEqual(self.monitor.state.contest_end,saved)

    def test_countdown_seconds_timezone_day_boundary_and_ended(self):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls(2030,1,1,tzinfo=timezone.utc)
        with patch.object(m,'datetime',Clock):
            for value,want in (('2030-01-01T09:00:01+09:00','00:00:01'),('2030-01-01T00:00:00.001Z','00:00:01'),('2030-01-02T00:00:00Z','1d 00:00:00'),('2030-01-01T00:00:00Z','ENDED'),('2029-12-31T23:59:59Z','ENDED')):
                with self.subTest(value=value):
                    self.assertEqual(m.competition_countdown({'contest_end':value})[0],want)
