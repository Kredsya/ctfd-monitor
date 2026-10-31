import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
from urllib.error import URLError
from scenarios import Scenario, m

class HttpContracts(Scenario):
    def test_token_is_sent_with_json_content_type_and_no_login_post(self):
        self.monitor.client.login()
        self.assertTrue(self.monitor.client.logged_in)
        path,headers=self.requests[-1]
        self.assertEqual(path,'/api/v1/users/me')
        self.assertEqual(headers['Authorization'],'Token fixture-token')
        self.assertEqual(headers['Content-Type'],'application/json')

    def test_status_matrix_does_not_fallback_on_auth_or_server_failure(self):
        for status in (400,401,403,408,429,500,502,503):
            with self.subTest(status=status):
                client=m.CTFdClient(self.url,'','','fixture-token')
                self.routes['/api/first']=(status,{'success':False,'message':'failure'}, {})
                self.ok('/api/second',[])
                self.requests.clear()
                with self.assertRaises(m.ApiError) as caught: client.request_json_routes(('/api/first','/api/second'))
                self.assertEqual(caught.exception.status,status)
                self.assertEqual([p for p,_ in self.requests],['/api/first'])

    def test_missing_route_fallback_and_cached_route_disappearing(self):
        for status in (404,405):
            with self.subTest(status=status):
                client=m.CTFdClient(self.url,'','','fixture-token')
                self.routes['/api/first']=(status,{},{}); self.ok('/api/second',[])
                client.request_json_routes(('/api/first','/api/second'))
                self.routes['/api/second']=(404,{},{}); self.ok('/api/first',[1])
                self.assertEqual(client.request_json_routes(('/api/first','/api/second'))['data'],[1])

    def test_response_matrix_html_malformed_nonobject_and_unsuccessful(self):
        for body in (b'<html>login</html>',b'{broken',b'[]',b'null',b'{"success":false}',b'{"data":[]}'):
            with self.subTest(body=body):
                self.routes['/api/test']=(200,body,{})
                with self.assertRaises(m.ApiError): self.monitor.client.request_json('/api/test')

    def test_transport_failure_is_a_controlled_api_error(self):
        for error in (URLError('offline'),TimeoutError('slow')):
            with self.subTest(error=type(error).__name__), patch.object(self.monitor.client.opener,'open',side_effect=error):
                with self.assertRaises(m.ApiError) as caught: self.monitor.client.request_json('/api/test')
                self.assertEqual(caught.exception.status,0)

    def test_retry_after_numeric_and_http_date(self):
        for value in ('90',format_datetime(datetime.now(timezone.utc)+timedelta(seconds=90))):
            with self.subTest(value=value):
                client=m.CTFdClient(self.url,'','','fixture-token')
                self.routes['/api/limited']=(429,{}, {'Retry-After':value})
                with self.assertRaises(m.ApiError): client.request_json('/api/limited')
                self.assertGreater(client.retry_until,time.monotonic()+80)
                self.requests.clear()
                with self.assertRaises(m.ApiError): client.request_json('/api/limited')
                self.assertEqual(self.requests,[])

    def test_real_redirect_does_not_send_token_to_other_origin(self):
        self.routes['/files/redirect']=(302,b'',{'Location':self.url.replace('127.0.0.1','localhost')+'/sink'})
        self.routes['/sink']=(200,b'file',{})
        with self.monitor.client.open_file('/files/redirect') as response: self.assertEqual(response.read(),b'file')
        self.assertEqual(self.requests[0][1]['Authorization'],'Token fixture-token')
        self.assertNotIn('Authorization',self.requests[-1][1])

    def test_api_absolute_external_url_is_rejected_before_credentials_leave(self):
        with self.assertRaises((m.ApiError,ValueError)):
            self.monitor.client.request_json(self.url.replace('127.0.0.1','localhost')+'/sink')
        self.assertEqual(self.requests,[],'API client must not send credentials to caller-supplied origins')
