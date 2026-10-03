"""Loopback endpoint that validates any channel document and returns its unified events."""
import http.client
import importlib
import json
import threading
import unittest

from test_posture_schema import document as posture_document


class ChannelServerTests(unittest.TestCase):
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

    def post(self, raw, duration='2.5', token=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if duration is not None:
            headers['X-ABA-Source-Duration'] = duration
        if token:
            headers['X-ABA-Token'] = self.server.token
        connection.request('POST', '/api/channel/validate', body=raw, headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read().decode('utf-8'))
        connection.close()
        return response.status, body

    def test_valid_document_returns_its_channel_binding_and_unified_events(self):
        self.server.engine = engine = object()
        status, body = self.post(json.dumps(posture_document()))
        self.assertEqual(status, 200, body)
        self.assertEqual((body['status'], body['channel']), ('valid', 'posture'))
        self.assertEqual(body['source_sha256'], posture_document()['source_sha256'])
        self.assertEqual(body['tracking_candidate_sha256'],
                         posture_document()['tracking_candidate_sha256'])
        self.assertEqual([e['event_id'] for e in body['events']], ['pos-000000'])
        self.assertEqual(body['events'][0]['origin'], 'measured')
        self.assertIs(self.server.engine, engine)

    def test_invalid_documents_and_requests_are_refused(self):
        fabricated = posture_document()
        fabricated['events'] = []
        raw = json.dumps(posture_document())
        for candidate in (json.dumps(fabricated), '[]', '{bad',
                          raw.replace('"posture_reading"', '"emotion_reading"')):
            with self.subTest(candidate=candidate[:30]):
                self.assertEqual(self.post(candidate)[0], 400)
        for duration in (None, '0', 'NaN', '1.0'):
            with self.subTest(duration=duration):
                self.assertEqual(self.post(raw, duration)[0], 400)
        self.assertEqual(self.post(raw, token=False)[0], 403)


if __name__ == '__main__':
    unittest.main()
