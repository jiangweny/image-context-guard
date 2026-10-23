"""Offline behavior tests: synthetic files, isolated homes, no real provider calls."""
import argparse
import base64
from contextlib import closing, contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vision = load('vision', 'skills/image-context-guard/scripts/read_image.py')
pruner = load('pruner', 'skills/image-context-guard/scripts/prune_history.py')
installer = load('installer', 'install.py')
demo = load('demo', 'tools/make_demo.py')
release = load('release', 'tools/check_release.py')


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='icg-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)


class VisionTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        (self.home / 'config.toml').write_text(
            'model="vision-test"\nmodel_provider="test"\n[model_providers.test]\n'
            'base_url="http://127.0.0.1:9000"\nwire_api="responses"\nenv_key="ICG_TEST_KEY"\n', encoding='utf-8')
        os.environ['ICG_TEST_KEY'] = 'synthetic-test-key'
        self.picture = self.root / 'frame.png'
        self.picture.write_bytes(demo.png_bytes())
        self.output = self.root / 'result.json'
        self.args = vision.parser().parse_args([
            '--codex-home', str(self.home), '--image', str(self.picture),
            '--prompt', 'Read the visible digits.', '--out', str(self.output)])
        self.request = mock.patch.object(vision, 'request_vision', return_value=('4827', {'input_tokens': 99}))
        self.api = self.request.start()
        self.addCleanup(self.request.stop)

    def test_request_is_independent_and_artifact_has_no_image_payload(self):
        result = vision.run(self.args)
        endpoint, key, payload, timeout = self.api.call_args.args
        self.assertEqual(endpoint, 'http://127.0.0.1:9000/responses')
        self.assertEqual(key, 'synthetic-test-key')
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        for forbidden in ('previous_response_id', 'conversation', 'tools'):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(len(payload['input']), 1)
        content = payload['input'][0]['content']
        self.assertEqual(base64.b64decode(content[1]['image_url'].split(',', 1)[1]), demo.png_bytes())
        for rendered in (self.output.read_text(encoding='utf-8'), json.dumps(result)):
            self.assertNotIn('data:image/', rendered)
            self.assertNotIn(key, rendered)
        self.assertEqual(result['text'], '4827')
        self.assertEqual(json.loads(self.output.read_text(encoding='utf-8'))['images'][0]['sha256'], vision.digest(demo.png_bytes()))

    def test_matching_cache_avoids_request(self):
        self.assertFalse(vision.run(self.args)['cached'])
        self.assertTrue(vision.run(self.args)['cached'])
        self.assertEqual(self.api.call_count, 1)

    def test_different_question_does_not_overwrite_result(self):
        vision.run(self.args)
        original = self.output.read_bytes()
        self.args.prompt = 'Different question'
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            vision.run(self.args)
        self.assertEqual(self.output.read_bytes(), original)

    def test_refresh_requires_explicit_overwrite(self):
        vision.run(self.args)
        self.args.refresh = True
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            vision.run(self.args)
        self.args.overwrite = True
        self.assertFalse(vision.run(self.args)['cached'])
        self.assertEqual(self.api.call_count, 2)

    def test_failed_request_redacts_key_and_payload(self):
        self.api.side_effect = RuntimeError('Failure synthetic-test-key data:image/png;base64,AAAA')
        with self.assertRaises(RuntimeError) as caught:
            vision.run(self.args)
        self.assertNotIn('synthetic-test-key', str(caught.exception))
        self.assertNotIn('AAAA', str(caught.exception))
        self.assertIn('[REDACTED]', str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_dry_run_needs_no_key_and_writes_nothing(self):
        os.environ.pop('ICG_TEST_KEY')
        self.args.dry_run = True
        self.assertEqual(vision.run(self.args)['history_items'], 0)
        self.api.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_budget_rejects_before_api(self):
        self.args.max_total_mib = 0.000001
        with self.assertRaisesRegex(ValueError, 'budget'):
            vision.run(self.args)
        self.api.assert_not_called()

    def test_configuration_cannot_be_overwritten(self):
        original = (self.home / 'config.toml').read_bytes()
        self.args.out = str(self.home / 'config.toml')
        with self.assertRaisesRegex(ValueError, 'must not overwrite'):
            vision.run(self.args)
        self.assertEqual((self.home / 'config.toml').read_bytes(), original)

    def test_active_profile_is_not_silently_ignored(self):
        config = self.home / 'config.toml'
        config.write_text('profile="custom"\n' + config.read_text(encoding='utf-8'), encoding='utf-8')
        with self.assertRaisesRegex(vision.VisionError, 'profiles'):
            vision.run(self.args)
        self.api.assert_not_called()

    def test_custom_headers_are_not_silently_ignored(self):
        config = self.home / 'config.toml'
        config.write_text(config.read_text(encoding='utf-8') + 'http_headers={"X-Test"="required"}\n', encoding='utf-8')
        with self.assertRaisesRegex(vision.VisionError, 'http_headers'):
            vision.run(self.args)

    def test_invalid_cache_is_handled_without_attribute_error(self):
        self.output.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            vision.run(self.args)

    def test_utf8_prompt_and_output(self):
        prompt = self.root / 'prompt.txt'
        prompt.write_text('读取数字并说明不确定之处。', encoding='utf-8')
        self.args.prompt = None
        self.args.prompt_file = str(prompt)
        self.api.return_value = ('数字为 4827。', None)
        self.assertEqual(vision.run(self.args)['text'], '数字为 4827。')
        self.assertIn('读取数字', self.api.call_args.args[2]['input'][0]['content'][0]['text'])

    def test_output_summary_is_bounded(self):
        self.api.return_value = ('x' * 9000, None)
        result = vision.run(self.args)
        self.assertEqual(len(result['text']), 8000)
        self.assertTrue(result['text_truncated'])
        self.assertEqual(len(json.loads(self.output.read_text(encoding='utf-8'))['text']), 9000)

    def test_review_is_fresh_and_first_pass_is_preserved(self):
        first = vision.run(self.args)
        original = self.output.read_bytes()
        review = self.root / 'review.json'
        self.args.review_pass = 'review'
        self.args.out = str(review)
        second = vision.run(self.args)
        self.assertEqual(self.api.call_count, 2)
        self.assertFalse(second['cached'])
        self.assertEqual(second['review_pass'], 'review')
        self.assertNotEqual(first['request_id'], second['request_id'])
        self.assertEqual(self.output.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'Review passes never reuse cache'):
            vision.run(self.args)
        self.assertEqual(self.api.call_count, 2)
        self.args.overwrite = True
        third = vision.run(self.args)
        self.assertEqual(self.api.call_count, 3)
        self.assertNotEqual(second['request_id'], third['request_id'])

    def test_structured_failure_does_not_write_a_result(self):
        self.api.side_effect = vision.VisionError('HTTP 429: wait', 'rate_limit', http_status=429, retryable=True)
        with self.assertRaises(vision.VisionError) as caught:
            vision.run(self.args)
        report = caught.exception.report()
        self.assertEqual(report['error_type'], 'rate_limit')
        self.assertEqual(report['http_status'], 429)
        self.assertIsInstance(report['elapsed_seconds'], float)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.api.call_count, 1)

    def test_nonfinite_budgets_are_rejected(self):
        for value in (float('nan'), float('inf'), 0, -1):
            self.args.timeout = value
            with self.assertRaisesRegex(ValueError, 'finite and positive'):
                vision.run(self.args)
        self.api.assert_not_called()

    def test_missing_auth_is_configuration_failure(self):
        os.environ.pop('ICG_TEST_KEY')
        with self.assertRaises(vision.VisionError) as caught:
            vision.run(self.args)
        self.assertEqual(caught.exception.category, 'configuration')
        self.api.assert_not_called()


class StreamTests(unittest.TestCase):
    def stream(self, *events):
        lines = []
        for event in events:
            lines.extend([('data: ' + json.dumps(event)).encode(), b''])
        return lines

    def test_completed_stream_returns_text(self):
        lines = self.stream({'type': 'response.output_text.delta', 'delta': '4827'},
                            {'type': 'response.completed', 'response': {'usage': {'input_tokens': 2}}})
        self.assertEqual(vision.consume_sse(lines), ('4827', {'input_tokens': 2}))

    def test_truncated_stream_is_not_a_success(self):
        with self.assertRaisesRegex(RuntimeError, 'without response.completed'):
            vision.consume_sse(self.stream({'type': 'response.output_text.delta', 'delta': 'partial'}))

    def test_incomplete_event_is_not_cached_as_success(self):
        with self.assertRaises(RuntimeError):
            vision.consume_sse(self.stream({'type': 'response.incomplete', 'response': {'status': 'incomplete'}}))

    def test_http_transport_disables_redirects_and_reads_stream(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.headers = {'content-type': 'text/event-stream'}
        response.iter_lines.return_value = self.stream(
            {'type': 'response.output_text.delta', 'delta': '4827'},
            {'type': 'response.completed', 'response': {}})
        with mock.patch('requests.post', return_value=response) as post:
            text, _ = vision._request_vision_http('http://127.0.0.1:9000/responses', 'fake', {}, 30)
        self.assertEqual(text, '4827')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertTrue(post.call_args.kwargs['stream'])

    def test_non_json_http_error_does_not_print_raw_body(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 502
        response.raw.read.return_value = b'<html>private-debug-body</html>'
        with mock.patch('requests.post', return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                vision._request_vision_http('http://127.0.0.1:9000/responses', 'fake', {}, 30)
        self.assertIn('HTTP 502', str(caught.exception))
        self.assertNotIn('private-debug-body', str(caught.exception))


class ErrorAndDeadlineTests(IsolatedTest):
    def test_permission_wrapped_by_proxy_is_classified_first(self):
        import requests
        error = requests.exceptions.ProxyError('Operation not permitted synthetic-test-key')
        report = vision.classify_error(error, 'synthetic-test-key').report()
        self.assertEqual(report['error_type'], 'permission')
        self.assertNotIn('synthetic-test-key', report['error'])
        self.assertFalse(report['retryable'])

    def test_proxy_auth_credentials_are_redacted(self):
        import requests
        error = requests.exceptions.ProxyError('Tunnel failed through https://user:private@proxy.invalid')
        report = vision.classify_error(error).report()
        self.assertEqual(report['error_type'], 'proxy')
        self.assertNotIn('user:private', report['error'])
        self.assertIn('[REDACTED]', report['error'])

    def test_timeout_and_connection_are_distinguished(self):
        import requests
        for error, expected in [(requests.exceptions.ReadTimeout('read stalled'), 'timeout'),
                                (requests.exceptions.ConnectionError('connection lost'), 'connection')]:
            self.assertEqual(vision.classify_error(error).category, expected)

    def test_http_errors_have_status_and_category(self):
        for status, expected in [(401, 'authentication'), (403, 'authentication'), (413, 'payload_too_large'),
                                 (429, 'rate_limit'), (503, 'service'), (400, 'request')]:
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status_code = status
            response.raw.read.return_value = b'{"error":{"message":"synthetic error"}}'
            with mock.patch('requests.post', return_value=response):
                with self.assertRaises(vision.VisionError) as caught:
                    vision._request_vision_http('http://127.0.0.1:9000/responses', 'fake', {}, 2)
            self.assertEqual(caught.exception.category, expected)
            self.assertEqual(caught.exception.http_status, status)

    def test_request_secret_and_payload_are_only_in_pipe(self):
        with mock.patch.object(vision, '_run_worker', return_value=('4827', None)) as worker:
            vision.request_vision('http://127.0.0.1:9000/responses', 'synthetic-key', {'image': 'synthetic-image'}, 1)
        command, request, deadline = worker.call_args.args
        self.assertNotIn('synthetic-key', ' '.join(command))
        self.assertNotIn('synthetic-image', ' '.join(command))
        self.assertEqual(request['key'], 'synthetic-key')
        self.assertEqual(deadline, 1)

    def test_worker_exits_and_returns_completed_result(self):
        script = self.root / 'worker.py'
        script.write_text('import json,sys\njson.load(sys.stdin)\nprint(json.dumps({"status":"ok","text":"4827","usage":None}))\n', encoding='utf-8')
        self.assertEqual(vision._run_worker([sys.executable, '-B', str(script)], {'test': True}, 10), ('4827', None))

    def test_worker_deadline_stops_stalled_request_and_reaps_process(self):
        script = self.root / 'stall.py'
        script.write_text('import json,sys,time\njson.load(sys.stdin)\nsys.stdout.write("partial response")\nsys.stdout.flush()\ntime.sleep(30)\n', encoding='utf-8')
        real_popen = subprocess.Popen
        processes = []
        def tracked(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process
        start = time.monotonic()
        with mock.patch.object(vision.subprocess, 'Popen', side_effect=tracked):
            with self.assertRaises(vision.VisionError) as caught:
                vision._run_worker([sys.executable, '-B', str(script)], {'test': True}, 0.4)
        self.assertEqual(caught.exception.category, 'total_timeout')
        self.assertLess(time.monotonic() - start, 8)
        self.assertIsNotNone(processes[0].poll())

    def test_worker_deadline_also_covers_blocked_stdin_upload(self):
        script = self.root / 'no_read.py'
        script.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        start = time.monotonic()
        with self.assertRaises(vision.VisionError) as caught:
            vision._run_worker([sys.executable, '-B', str(script)], {'payload': 'x' * 2_000_000}, 0.4)
        self.assertEqual(caught.exception.category, 'total_timeout')
        self.assertLess(time.monotonic() - start, 8)

    def test_deadline_does_not_depend_on_communicate_timeout(self):
        # Windows can block writing stdin before communicate checks its timeout.
        # Exercise an uninterruptible communicate on every platform.
        script = self.root / 'blocked_pipe.py'
        script.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        real_communicate = subprocess.Popen.communicate
        real_popen = subprocess.Popen
        processes = []
        threads_before = set(threading.enumerate())

        def blocking_communicate(process, input=None, timeout=None):
            return real_communicate(process, input=input)

        def tracked(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        start = time.monotonic()
        with mock.patch.object(subprocess.Popen, 'communicate', blocking_communicate):
            with mock.patch.object(vision.subprocess, 'Popen', side_effect=tracked):
                with self.assertRaises(vision.VisionError) as caught:
                    vision._run_worker([sys.executable, '-B', str(script)],
                                       {'payload': 'x' * 2_000_000}, 0.4)
        self.assertEqual(caught.exception.category, 'total_timeout')
        self.assertLess(time.monotonic() - start, 8)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(all(pipe.closed for pipe in
                            (processes[0].stdin, processes[0].stdout, processes[0].stderr)))
        self.assertFalse(set(threading.enumerate()) - threads_before)

    def test_pipe_error_reaps_worker_and_closes_streams(self):
        script = self.root / 'pipe_error.py'
        script.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        real_popen = subprocess.Popen
        processes = []
        threads_before = set(threading.enumerate())

        def tracked(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(subprocess.Popen, 'communicate', side_effect=OSError('pipe failure')):
            with mock.patch.object(vision.subprocess, 'Popen', side_effect=tracked):
                with self.assertRaisesRegex(OSError, 'pipe failure'):
                    vision._run_worker([sys.executable, '-B', str(script)], {}, 10)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(all(pipe.closed for pipe in
                            (processes[0].stdin, processes[0].stdout, processes[0].stderr)))
        self.assertFalse(set(threading.enumerate()) - threads_before)

    def test_raw_worker_stderr_is_not_exposed(self):
        script = self.root / 'failed.py'
        script.write_text('import sys\nsys.stderr.write("private-worker-detail")\nsys.exit(2)\n', encoding='utf-8')
        with self.assertRaises(vision.VisionError) as caught:
            vision._run_worker([sys.executable, '-B', str(script)], {}, 10)
        self.assertEqual(caught.exception.category, 'worker')
        self.assertNotIn('private-worker-detail', str(caught.exception))

    def test_cli_emits_structured_config_error_without_credentials(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'icg.py'), 'read',
                                 '--codex-home', str(self.home), '--image', str(ROOT / 'examples/demo.png'),
                                 '--prompt', 'test', '--out', str(self.root / 'result.json')],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report['error_type'], 'configuration')
        self.assertEqual(report['phase'], 'configuration')

    def test_actual_worker_protocol_without_network(self):
        # A temporary requests shim exercises the real child process and JSON pipe.
        # This is local test data, not a provider or a modification of installed packages.
        shim = self.root / 'shim'
        shim.mkdir()
        (shim / 'requests.py').write_text(
            'import json\n'
            'class Response:\n'
            '    status_code = 200\n'
            '    headers = {"content-type": "text/event-stream"}\n'
            '    def __enter__(self): return self\n'
            '    def __exit__(self, *args): pass\n'
            '    def iter_lines(self):\n'
            '        yield ("data: " + json.dumps({"type":"response.output_text.delta","delta":"数字 4827"})).encode()\n'
            '        yield b""\n'
            '        yield b\'data: {"type":"response.completed","response":{"usage":{"input_tokens":1}}}\'\n'
            '        yield b""\n'
            'def post(endpoint, **kwargs):\n'
            '    assert kwargs["headers"]["Authorization"] == "Bearer fake-worker-key"\n'
            '    assert kwargs["json"] == {"synthetic": True}\n'
            '    assert kwargs["allow_redirects"] is False\n'
            '    return Response()\n', encoding='utf-8')
        with mock.patch.dict(os.environ, {'PYTHONPATH': str(shim)}):
            text, usage = vision.request_vision('https://synthetic.invalid/responses', 'fake-worker-key', {'synthetic': True}, 10)
        self.assertEqual(text, '数字 4827')
        self.assertEqual(usage, {'input_tokens': 1})


class HistoryTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.sid = str(uuid.uuid4())
        folder = self.home / 'sessions'
        folder.mkdir()
        self.path = folder / ('rollout-' + self.sid + '.jsonl')
        image = {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(demo.png_bytes()).decode(), 'detail': 'high'}
        self.observed = {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Observed 4827; preserve position 20,30.'}]}
        self.call = {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'original-call', 'input': 'read original.png'}}
        self.items = [
            {'type': 'session_meta', 'payload': {'id': self.sid}}, self.call,
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'original-call', 'output': [image]}},
            {'type': 'compacted', 'payload': {'replacement_history': [self.observed], 'guardian_history': [image]}},
            {'type': 'response_item', 'payload': self.observed}]
        self.raw = self.encode(self.items)
        self.path.write_bytes(self.raw)
        self.checkpoint = self.root / 'handoff.md'
        self.checkpoint.write_text('Observed 4827. Verify position against original.png.', encoding='utf-8')

    @staticmethod
    def encode(items):
        return b''.join(json.dumps(item).encode() + bytes([10]) for item in items)

    def require_posix(self):
        if pruner.fcntl is None:
            self.skipTest('History mutation requires POSIX locks; audit tests still run.')

    def test_audit_distinguishes_disk_history_and_compacted_history(self):
        info = pruner.audit(self.path)
        self.assertEqual(info['embedded_image_entries'], 2)
        self.assertEqual(info['estimated_history_image_entries'], 0)
        self.assertEqual(info['disk_bytes'], len(self.raw))
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_preview_does_not_write(self):
        result = pruner.prune(self.home, self.path, self.checkpoint, False)
        self.assertEqual(result['status'], 'preview')
        self.assertFalse((self.home / 'image-context-backups').exists())
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_current_history_is_refused(self):
        self.require_posix()
        os.environ['CODEX_THREAD_ID'] = self.sid
        with self.assertRaisesRegex(ValueError, 'current conversation'):
            pruner.prune(self.home, self.path, self.checkpoint, True)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_locked_history_is_refused(self):
        self.require_posix()
        locks = self.home / 'thread-writer-locks'
        locks.mkdir()
        with (locks / (self.sid + '.lock')).open('wb') as handle:
            pruner.fcntl.flock(handle, pruner.fcntl.LOCK_EX | pruner.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'writer lock'):
                pruner.prune(self.home, self.path, self.checkpoint, True)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_cleanup_preserves_text_order_and_tool_ids_and_restores_exactly(self):
        self.require_posix()
        result = pruner.prune(self.home, self.path, self.checkpoint, True)
        self.assertEqual(result['removed_image_entries'], 2)
        self.assertEqual(pruner.audit(self.path)['embedded_image_entries'], 0)
        cleaned = [json.loads(line) for line in self.path.read_bytes().splitlines()]
        self.assertEqual(len(cleaned), len(self.items))
        self.assertEqual(cleaned[1], self.call)
        self.assertEqual(cleaned[2]['payload']['call_id'], 'original-call')
        self.assertEqual(cleaned[4]['payload'], self.observed)
        self.assertEqual(Path(result['backup']).read_bytes(), self.raw)
        pruner.restore(self.home, result['manifest'], True)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_restore_refuses_new_messages(self):
        self.require_posix()
        result = pruner.prune(self.home, self.path, self.checkpoint, True)
        newer = self.path.read_bytes() + self.encode([{'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'new'}}])
        self.path.write_bytes(newer)
        with self.assertRaisesRegex(ValueError, 'changed'):
            pruner.restore(self.home, result['manifest'], True)
        self.assertEqual(self.path.read_bytes(), newer)

    def test_unknown_image_metadata_is_refused_unchanged(self):
        self.require_posix()
        self.items[2]['payload']['output'][0]['unknown'] = 'preserve me'
        raw = self.encode(self.items)
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Unknown input_image'):
            pruner.prune(self.home, self.path, self.checkpoint, True)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_truncated_jsonl_is_refused(self):
        self.path.write_bytes(self.raw[:-1])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            pruner.audit(self.path)

    def test_index_schema_change_falls_back_to_filename(self):
        import sqlite3
        with closing(sqlite3.connect(self.home / 'state_5.sqlite')):
            pass
        self.assertEqual(pruner.session_path(self.home, self.sid), self.path.resolve())

    def test_index_connections_close_on_success_and_schema_fallback(self):
        import sqlite3
        database = self.home / 'state_5.sqlite'
        connect = sqlite3.connect
        for valid_schema in (False, True):
            with self.subTest(valid_schema=valid_schema):
                with closing(connect(database)) as connection:
                    if valid_schema:
                        connection.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT)')
                        connection.execute('INSERT INTO threads VALUES (?, ?)', (self.sid, str(self.path)))
                        connection.commit()
                original = database.read_bytes()
                connections = []

                def tracked(*args, **kwargs):
                    connection = connect(*args, **kwargs)
                    connections.append(connection)
                    self.addCleanup(connection.close)
                    return connection

                with mock.patch.object(pruner.sqlite3, 'connect', side_effect=tracked):
                    self.assertEqual(pruner.session_path(self.home, self.sid), self.path.resolve())
                self.assertEqual(len(connections), 1)
                # Retain a reference so garbage collection cannot conceal a leaked connection.
                with self.assertRaises(sqlite3.ProgrammingError):
                    connections[0].execute('SELECT 1')
                self.assertEqual(database.read_bytes(), original)
                database.unlink()

    def test_history_selection_normalizes_home(self):
        alias = self.home / 'sessions' / '..'
        for selector in (self.sid, str(self.path)):
            with self.subTest(selector=selector):
                self.assertEqual(pruner.session_path(alias, selector), self.path.resolve())

    def test_history_selection_accepts_symlinked_home(self):
        alias = self.root / 'codex-alias'
        try:
            alias.symlink_to(self.home.resolve(), target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Directory symlinks are unavailable: ' + str(error))
        self.assertEqual(pruner.session_path(alias, self.sid), self.path.resolve())

    def test_restore_normalizes_home(self):
        self.require_posix()
        result = pruner.prune(self.home, self.path, self.checkpoint, True)
        restored = pruner.restore(self.home / 'sessions' / '..', result['manifest'], True)
        self.assertEqual(restored['status'], 'restored')
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_restore_refuses_manifest_outside_backup_directory(self):
        manifest = self.root / 'outside-manifest.json'
        manifest.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inside this Codex home'):
            pruner.restore(self.home / 'sessions' / '..', manifest, False)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_outside_history_directory_is_refused(self):
        outside = self.root / 'outside.jsonl'
        outside.write_bytes(self.raw)
        for home in (self.home, self.home / 'sessions' / '..'):
            with self.subTest(home=home):
                with self.assertRaisesRegex(ValueError, 'under this Codex home'):
                    pruner.session_path(home, str(outside))

    def test_missing_posix_support_is_clear_and_non_destructive(self):
        with mock.patch.object(pruner, 'fcntl', None):
            with self.assertRaisesRegex(ValueError, 'POSIX'):
                pruner.prune(self.home, self.path, self.checkpoint, True)
        self.assertEqual(self.path.read_bytes(), self.raw)


class InstallTests(IsolatedTest):
    def arguments(self, **changes):
        args = argparse.Namespace(codex_home=str(self.home), skills_dir=None,
                                  with_global_rule=False, replace=False, dry_run=False)
        for key, value in changes.items():
            setattr(args, key, value)
        return args

    def test_dry_run_creates_no_files(self):
        result = installer.install(self.arguments(dry_run=True))
        self.assertEqual(result['status'], 'preview')
        self.assertEqual(list(self.home.iterdir()), [])

    def test_install_is_self_contained_and_records_interpreter(self):
        result = installer.install(self.arguments())
        target = Path(result['skill'])
        for name in installer.FILES:
            self.assertEqual((target / name).read_bytes(), (installer.SOURCE / name).read_bytes())
        self.assertEqual(json.loads((target / 'runtime.json').read_text(encoding='utf-8'))['python'], sys.executable)
        self.assertFalse((self.home / 'AGENTS.md').exists())

    def test_global_rule_preserves_existing_content_and_replacement_backup(self):
        rules = self.home / 'AGENTS.md'
        original = 'Existing house rules.\n'
        rules.write_text(original, encoding='utf-8')
        first = installer.install(self.arguments(with_global_rule=True))
        self.assertTrue(rules.read_text(encoding='utf-8').startswith(original))
        self.assertEqual((Path(first['backup']) / 'AGENTS.md.bak').read_text(encoding='utf-8'), original)
        second = installer.install(self.arguments(with_global_rule=True, replace=True))
        self.assertEqual(rules.read_text(encoding='utf-8').count(installer.START), 1)
        self.assertTrue((Path(second['backup']) / 'skill' / 'SKILL.md').exists())

    def test_existing_skill_requires_replace(self):
        installer.install(self.arguments())
        with self.assertRaisesRegex(ValueError, '--replace'):
            installer.install(self.arguments())

    def test_override_file_prevents_global_rule_install(self):
        (self.home / 'AGENTS.override.md').write_text('Override', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'AGENTS.override.md'):
            installer.install(self.arguments(with_global_rule=True))
        self.assertFalse((self.home / 'skills').exists())

    def test_custom_discovery_directory(self):
        custom = self.root / 'custom-skills'
        result = installer.install(self.arguments(skills_dir=str(custom)))
        self.assertEqual(Path(result['skill']), custom.resolve() / 'image-context-guard')

    def test_custom_discovery_directory_normalizes_parent_alias(self):
        custom = self.home / '..' / 'custom-skills'
        result = installer.install(self.arguments(skills_dir=str(custom)))
        self.assertEqual(Path(result['skill']), custom.resolve() / 'image-context-guard')
        self.assertTrue((Path(result['skill']) / 'SKILL.md').is_file())

    def test_backend_preferences_persist_on_replacement(self):
        first = installer.install(self.arguments(backend='native-agent', max_native_agents=1, no_progress_seconds=180))
        second = installer.install(self.arguments(replace=True))
        self.assertEqual(second['backend'], 'native-agent')
        self.assertEqual(second['max_native_agents'], 1)
        self.assertEqual(second['no_progress_seconds'], 180)
        runtime = json.loads((Path(first['skill']) / 'runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(runtime['backend'], 'native-agent')

    def test_new_install_defaults_to_auto(self):
        result = installer.install(self.arguments())
        self.assertEqual(result['backend'], 'auto')
        self.assertEqual(result['max_native_agents'], 2)

    def test_invalid_scheduling_limits_are_rejected_before_write(self):
        for changes in ({'no_progress_seconds': 0}, {'max_native_agents': 0}, {'backend': 'unknown'}):
            with self.assertRaises(ValueError):
                installer.install(self.arguments(**changes))
        self.assertFalse((self.home / 'skills').exists())


class CliTests(IsolatedTest):
    def test_helpers_accept_explicit_home_without_user_profile(self):
        # Path.home fails on Windows when USERPROFILE/HOMEPATH are absent.
        with mock.patch.object(Path, 'home', side_effect=RuntimeError('Could not determine home directory.')):
            args = vision.parser().parse_args([
                '--codex-home', str(self.home), '--image', str(ROOT / 'examples/demo.png'),
                '--prompt', 'test', '--out', str(self.root / 'result.json')])
            with self.assertRaises(vision.VisionError) as caught:
                vision.run(args)
            self.assertEqual(caught.exception.category, 'configuration')
            with mock.patch.object(sys, 'argv', ['install.py', '--codex-home', str(self.home), '--dry-run']):
                with mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                    installer.main()
                self.assertEqual(json.loads(output.getvalue())['status'], 'preview')
            with mock.patch.object(sys, 'argv', ['prune_history.py', '--codex-home', str(self.home),
                                                'audit', '--session', str(uuid.uuid4())]):
                with mock.patch.object(pruner, 'session_path', side_effect=ValueError('synthetic missing session')):
                    with self.assertRaisesRegex(ValueError, 'synthetic missing session'):
                        pruner.main()

    def test_helper_help_does_not_require_user_profile(self):
        with mock.patch.object(Path, 'home', side_effect=RuntimeError('Could not determine home directory.')):
            for name, entrypoint in (('read_image.py', lambda: vision.parser().parse_args()),
                                     ('prune_history.py', pruner.main), ('install.py', installer.main)):
                with self.subTest(helper=name):
                    with mock.patch.object(sys, 'argv', [name, '--help']):
                        with mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                            with self.assertRaises(SystemExit) as caught:
                                entrypoint()
                        self.assertEqual(caught.exception.code, 0)
                        self.assertIn('usage:', output.getvalue())

    def test_codex_home_environment_does_not_require_user_profile(self):
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(self.home)}):
            with mock.patch.object(Path, 'home', side_effect=RuntimeError('Could not determine home directory.')):
                args = vision.parser().parse_args([
                    '--image', str(ROOT / 'examples/demo.png'), '--prompt', 'test',
                    '--out', str(self.root / 'result.json')])
                self.assertEqual(args.codex_home, str(self.home))

    def test_cli_help_routes_to_each_helper(self):
        for command in ([], ['read'], ['history']):
            result = subprocess.run([sys.executable, str(ROOT / 'icg.py'), *command, '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('usage:', result.stdout)

    def test_generated_fixture_is_reproducible(self):
        self.assertEqual((ROOT / 'examples' / 'demo.png').read_bytes(), demo.png_bytes())

    def test_release_check_detects_private_files(self):
        (self.root / 'auth.json').write_text('{}', encoding='utf-8')
        result = release.check(self.root)
        self.assertEqual(result['status'], 'fail')
        self.assertTrue(any('auth.json' in error for error in result['errors']))


if __name__ == '__main__':
    unittest.main()
