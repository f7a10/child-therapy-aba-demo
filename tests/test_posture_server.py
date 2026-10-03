"""Loopback validation endpoint for the local posture document; no model required."""
import http.client
import importlib
import json
import threading
import unittest

from test_posture_schema import document


class PostureServerTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('aba_demo.server')
        self.server = self.module.create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, raw, headers=None, token=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        all_headers = {'Content-Type': 'application/json'}
        if token:
            all_headers['X-ABA-Token'] = self.server.token
        all_headers.update(headers or {})
        connection.request('POST', '/api/posture/validate', body=raw, headers=all_headers)
        response = connection.getresponse()
        body = response.read().decode('utf-8')
        connection.close()
        return response.status, body

    def test_valid_document_is_accepted_without_touching_engine_state(self):
        self.server.engine = engine = object()
        raw = json.dumps(document()).encode('utf-8')
        status, body = self.post(raw, {'X-ABA-Source-Duration': '2.5'})
        self.assertEqual((status, json.loads(body)), (200, {'status': 'valid'}))
        self.assertIs(self.server.engine, engine)

    def test_invalid_documents_durations_and_requests_are_refused(self):
        fabricated = document()
        fabricated['events'] = []
        raw = json.dumps(document())
        for candidate in (json.dumps(fabricated), '[]', '{bad',
                          raw.replace('"posture_reading"', '"movement_reading"')):
            with self.subTest(candidate=candidate[:30]):
                self.assertEqual(self.post(candidate, {'X-ABA-Source-Duration': '2.5'})[0], 400)
        for duration in (None, '0', 'NaN', '1.0'):
            with self.subTest(duration=duration):
                headers = {} if duration is None else {'X-ABA-Source-Duration': duration}
                self.assertEqual(self.post(raw, headers)[0], 400)
        self.assertEqual(self.post(raw, {'X-ABA-Source-Duration': '2.5'}, token=False)[0], 403)
        oversized = raw.encode('utf-8') + b' ' * (self.module.MAX_JSON_BYTES + 1)
        status, body = self.post(oversized, {'X-ABA-Source-Duration': '2.5'})
        self.assertEqual(status, 200, body)


if __name__ == '__main__':
    unittest.main()
