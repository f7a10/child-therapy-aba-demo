"""No-network tests for the explicit local .env synthetic context probe."""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


class LocalOpenRouterProbeTests(unittest.TestCase):
    def test_reads_only_explicit_local_key_file_without_changing_environment(self):
        from scripts.probe_openrouter_context import read_local_key

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            self.assertIsNone(read_local_key(path))
            path.write_text('OTHER=not-a-key\nOPENROUTER_API_KEY=synthetic-token\n', encoding='utf-8')
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'unrelated-environment'}, clear=True):
                self.assertEqual(read_local_key(path), 'synthetic-token')
                self.assertEqual(os.environ['OPENROUTER_API_KEY'], 'unrelated-environment')
            path.write_text('OPENROUTER_API_KEY=\n', encoding='utf-8')
            self.assertIsNone(read_local_key(path))
            path.write_text('OPENROUTER_API_KEY=first\nOPENROUTER_API_KEY=second\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_local_key(path)

    def test_synthetic_probe_uses_local_key_privacy_and_completion_budget(self):
        from scripts.probe_openrouter_context import run_probe

        output = {
            'activity_suggestion': 'unclear', 'activity_status': 'not_observable',
            'target_material_interaction': 'not_observable',
            'adult_target_interaction_visible': 'not_observable', 'evidence_times': [],
        }
        model = 'dots-studio/dots-3-note-preview:free'
        envelope = {
            'model': model,
            'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps(output),
            }}],
            'openrouter_metadata': {
                'requested': model,
                'endpoints': {'available': [{
                    'provider': 'fixture-provider',
                    'model': 'dots-studio/dots-3-note-preview-20260813:free',
                    'selected': True,
                }]},
            },
        }
        transport = Mock(return_value=(200, json.dumps(envelope).encode('utf-8')))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('OPENROUTER_API_KEY=synthetic-token\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(run_probe(key_path=path, model=model, transport=transport),
                                 'success')
                self.assertNotIn('OPENROUTER_API_KEY', os.environ)
        transport.assert_called_once()
        request = transport.call_args.kwargs
        self.assertEqual(request['headers']['Authorization'], 'Bearer synthetic-token')
        self.assertEqual(request['headers']['X-OpenRouter-Metadata'], 'enabled')
        body = json.loads(request['body'])
        self.assertEqual(body['max_tokens'], 4096)
        self.assertEqual(body['provider'], {
            'require_parameters': True, 'data_collection': 'deny',
            'allow_fallbacks': False,
        })
        self.assertTrue(body['response_format']['json_schema']['strict'])
        self.assertEqual(sum(part['type'] == 'image_url'
                             for part in body['messages'][1]['content']), 2)

    def test_missing_key_fails_before_transport(self):
        from scripts.probe_openrouter_context import run_probe

        with tempfile.TemporaryDirectory() as tmp:
            transport = Mock()
            result = run_probe(key_path=Path(tmp) / '.env', transport=transport)
        self.assertEqual(result, 'provider_not_configured')
        transport.assert_not_called()

    def test_cli_prints_only_stable_code_when_provider_error_contains_secret(self):
        from scripts import probe_openrouter_context as probe

        output, errors = StringIO(), StringIO()
        with (patch.object(probe, 'read_local_key', return_value='synthetic-token'),
              patch('aba_demo.openrouter_context._http_transport',
                    side_effect=RuntimeError('synthetic-token provider-payload')),
              patch.object(sys, 'argv', ['probe_openrouter_context.py']),
              redirect_stdout(output), redirect_stderr(errors)):
            probe.main()
        self.assertEqual(output.getvalue(), 'RESULT: provider_unavailable\n')
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
