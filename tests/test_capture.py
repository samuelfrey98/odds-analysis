from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from http.client import IncompleteRead
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from odds_analysis.adapters.live_odds_api import CaptureError, Client, MAX_BYTES, _NoRedirect, quota
from odds_analysis.capture import capture, select_event
from odds_analysis.cli import main

KEY = 'dummy-key-for-offline-tests-only'
NOW = datetime(2030, 1, 15, 12, 5, tzinfo=timezone.utc)


class FixedClock:
    @staticmethod
    def now(tz):
        return NOW


def headers(last=0, remaining=500):
    return {'x-requests-last': str(last), 'x-requests-remaining': str(remaining), 'x-requests-used': str(500-remaining)}


class Response:
    status = 200

    def __init__(self, data, *, cost=0, raw=None, remaining=500):
        self.raw = json.dumps(data).encode() if raw is None else raw
        self.headers = headers(cost, remaining)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.raw[:limit]


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def snapshot():
    source = json.loads((Path(__file__).resolve().parents[1]/'examples'/'saved_event_odds.json').read_text())[0]
    # Use one provider's exact spelling consistently; no alias inference in capture.
    source['bookmakers'][0]['markets'][0]['outcomes'][0]['description'] = 'Alex Example'
    source['bookmakers'][0]['markets'][0]['outcomes'][1]['description'] = 'Alex Example'
    for name in ('betmgm', 'betrivers'):
        book = deepcopy(source['bookmakers'][0])
        book['key'] = name
        source['bookmakers'].append(book)
    return source


def event_list(data):
    return [{key: data[key] for key in ('id', 'sport_key', 'commence_time')}]


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        original = Path.cwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, original)
        self.source = snapshot()
        self.transport = Transport([Response(event_list(self.source)), Response(self.source, cost=1, remaining=499)])
        for context in (patch.dict(os.environ, {'ODDS_API_KEY': KEY}),
                        patch('odds_analysis.adapters.live_odds_api.build_opener', return_value=self.transport),
                        patch('odds_analysis.adapters.live_odds_api.datetime', FixedClock)):
            context.start()
            self.addCleanup(context.stop)

    def run_capture(self, **kwargs):
        return capture(output=Path('private/run'), **kwargs)

    def test_end_to_end_two_requests_one_market_preserves_source_times(self):
        audit, output = self.run_capture()
        self.assertEqual(audit['status'], 'analyzed')
        self.assertEqual(audit['comparisons'], 2)
        self.assertEqual([r['quota']['last'] for r in audit['requests']], [0, 1])
        self.assertEqual(len(self.transport.calls), 2)
        url, timeout = self.transport.calls[-1]
        parts = urlsplit(url.full_url)
        self.assertEqual(parts.scheme, 'https')
        self.assertEqual(parts.netloc, 'api.the-odds-api.com')
        self.assertEqual(parse_qs(parts.query), {'apiKey': [KEY], 'regions': ['us'], 'markets': ['player_points'],
                                              'oddsFormat': ['american'], 'dateFormat': ['iso']})
        self.assertEqual(timeout, 30)
        self.assertEqual((output/'snapshot.json').read_bytes(), json.dumps(self.source).encode())
        report = json.loads((output/'report.json').read_text())
        self.assertEqual(report['as_of'], NOW.isoformat())
        self.assertIn('2030-01-15T12:00:00+00:00', (output/'quotes.csv').read_text())
        self.assertIn('2030-01-15T12:02:00+00:00', (output/'quotes.csv').read_text())
        self.assertIn('gap', (output/'report.md').read_text())
        for path in output.iterdir():
            self.assertNotIn(KEY, path.read_text())
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual((output/'.gitignore').read_text(), '*\n!.gitignore\n')
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)

    def test_preflight_requires_available_quota_before_paid_call(self):
        for q in ({}, headers(0, 0), headers(2, 500), {'x-requests-last':'0','x-requests-remaining': KEY}):
            with self.subTest(q=q):
                self.transport.calls.clear()
                first = Response(event_list(self.source))
                first.headers = q
                self.transport.responses = [first]
                audit, _ = capture(output=Path('private')/str(len(list(Path('private').glob('*'))) if Path('private').exists() else 0))
                self.assertEqual(audit['status'], 'failed')
                self.assertEqual(len(self.transport.calls), 1)
                self.assertIn('no odds request', audit['error'])

    def test_no_upcoming_or_unknown_selected_event_does_not_spend_credit(self):
        for identifier in (None, 'unknown'):
            self.transport.calls.clear()
            self.transport.responses = [Response([] if identifier is None else event_list(self.source))]
            audit, _ = capture(output=Path('private')/str(identifier), event_id=identifier)
            self.assertEqual(audit['status'], 'failed')
            self.assertEqual(len(self.transport.calls), 1)

    def test_invalid_configuration_and_existing_or_public_output_make_no_requests(self):
        Path('private/existing').mkdir(parents=True)
        for kwargs in ({'output':Path('reports/public')}, {'output':Path('private')},
                       {'output':Path('private/existing')}, {'output':Path('private/../outside')},
                       {'event_id':'../escape'}, {'reference_books':['fanduel']},
                       {'target_book':'not a key'}, {'reference_books':[]}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, OSError)):
                capture(**kwargs)
        self.assertEqual(self.transport.calls, [])

    def test_symlink_private_storage_is_rejected_before_request(self):
        Path('elsewhere').mkdir()
        Path('private').symlink_to(Path('elsewhere').resolve(), target_is_directory=True)
        with self.assertRaises(CaptureError):
            self.run_capture()
        self.assertEqual(self.transport.calls, [])

    def test_unexpected_paid_cost_is_recorded_and_no_retry_occurs(self):
        self.transport.responses[1].headers = headers(2, 498)
        audit, output = self.run_capture()
        self.assertEqual(audit['status'], 'failed')
        self.assertEqual(audit['requests'][1]['quota']['last'], 2)
        self.assertTrue((output/'snapshot.json').exists())
        self.assertFalse((output/'report.md').exists())
        self.assertEqual(len(self.transport.calls), 2)

    def test_partial_import_is_explicit_and_diagnostics_are_saved(self):
        self.source['bookmakers'][0]['markets'][0]['outcomes'][0]['point'] = 24
        self.transport.responses[1] = Response(self.source, cost=1, remaining=499)
        audit, output = self.run_capture()
        self.assertEqual(audit['status'], 'import_blocked')
        self.assertFalse((output/'quotes.csv').exists())
        self.assertGreater(audit['import_issue_count'], 0)
        self.assertTrue((output/'import-diagnostics.json').exists())
        self.transport.responses = [Response(event_list(self.source)), Response(self.source, cost=1, remaining=499)]
        audit, _ = capture(output=Path('private/partial'), allow_partial=True)
        self.assertEqual(audit['status'], 'analyzed')
        self.assertTrue(audit['allow_partial'])

    def test_empty_odds_and_missing_target_remain_visible(self):
        for books, expected in (([], 'import_blocked'), ([b for b in self.source['bookmakers'] if b['key']!='fanduel'], 'no_target_comparisons')):
            source = deepcopy(self.source)
            source['bookmakers'] = books
            self.transport.responses = [Response(event_list(source)), Response(source, cost=0)]
            audit, _ = capture(output=Path('private')/expected)
            self.assertEqual(audit['status'], expected)

    def test_wrong_event_or_sport_and_event_that_started_during_capture_fail(self):
        for field, value in (('id','wrong'), ('sport_key','wrong'), ('commence_time',NOW.isoformat())):
            source = deepcopy(self.source)
            source[field] = value
            self.transport.responses = [Response(event_list(self.source)), Response(source, cost=1)]
            audit, output = capture(output=Path('private')/field)
            self.assertEqual(audit['status'], 'failed')
            self.assertTrue((output/'snapshot.json').exists())
            self.assertFalse((output/'report.md').exists())

    def test_network_and_http_failures_are_audited_without_secret_or_response_body(self):
        for index, error in enumerate((URLError(KEY), TimeoutError(KEY), IncompleteRead(KEY.encode()),
                HTTPError('https://example.test/?apiKey='+KEY,401,KEY,headers(),BytesIO(KEY.encode())),
                HTTPError('https://example.test/?apiKey='+KEY,429,KEY,headers(),BytesIO(KEY.encode())),
                HTTPError('https://example.test/?apiKey='+KEY,500,KEY,headers(),BytesIO(KEY.encode())))):
            self.transport.responses = [Response(event_list(self.source)), error]
            audit, output = capture(output=Path('private')/str(index))
            self.assertEqual(audit['status'], 'failed')
            self.assertNotIn(KEY, (output/'capture.json').read_text())
            self.assertFalse((output/'snapshot.json').exists())

    def test_raw_and_json_escaped_credential_echoes_are_not_saved(self):
        for index, raw in enumerate((json.dumps({'echo':KEY}).encode(),
                                    ('{"echo":"'+''.join('\\u%04x'%ord(c) for c in KEY)+'"}').encode())):
            self.transport.responses = [Response(event_list(self.source)), Response(None, raw=raw, cost=1)]
            audit, output = capture(output=Path('private')/str(index))
            self.assertEqual(audit['status'], 'failed')
            self.assertFalse((output/'snapshot.json').exists())
            self.assertNotIn(KEY, (output/'capture.json').read_text())

    def test_invalid_or_oversized_json_is_not_saved(self):
        for index, raw in enumerate((b'not json', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'\xff', b' '*(MAX_BYTES+1))):
            self.transport.responses = [Response(event_list(self.source)), Response(None, raw=raw, cost=1)]
            audit, output = capture(output=Path('private')/str(index))
            self.assertEqual(audit['status'], 'failed')
            self.assertFalse((output/'snapshot.json').exists())

    def test_cli_exit_codes_and_console_credential_redaction(self):
        with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
            self.assertEqual(main(['capture','--output','private/cli']), 0)
        self.assertIn('remaining=499', stdout.getvalue())
        self.assertNotIn(KEY, stdout.getvalue()+stderr.getvalue())
        self.transport.responses = [Response(event_list(self.source)), Response({**self.source,'bookmakers':[]},cost=0)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(['capture','--output','private/empty']), 1)
        with patch.dict(os.environ, {'ODDS_API_KEY':''}), redirect_stderr(StringIO()):
            self.assertEqual(main(['capture','--output','private/no-key']), 2)


class ClientPolicyTests(unittest.TestCase):
    def test_quota_values_are_allowlisted_nonnegative_integers(self):
        self.assertEqual(quota({'x-requests-last':'-1','x-requests-used':'secret','x-requests-remaining':'123'}),
                         {'last':None,'used':None,'remaining':123})

    def test_redirects_are_not_followed(self):
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'moved',{},'https://elsewhere.test'))

    def test_client_request_order_and_count_are_bounded(self):
        transport = Transport([Response([]), Response({})])
        with patch('odds_analysis.adapters.live_odds_api.build_opener', return_value=transport):
            client = Client(KEY)
            with self.assertRaises(CaptureError):
                client.get('odds','id')
            client.get('events')
            client.get('odds','id')
            for operation in ('events','odds','other'):
                with self.assertRaises(CaptureError):
                    client.get(operation,'id')
        self.assertEqual(len(transport.calls), 2)

    def test_event_selection_excludes_started_malformed_and_wrong_sport(self):
        base = event_list(snapshot())[0]
        events = [{**base,'id':'b'}, {**base,'id':'a'}, {**base,'commence_time':NOW.isoformat()},
                  {**base,'commence_time':'bad'}, {**base,'sport_key':'other'}, None]
        self.assertEqual(select_event(events,NOW,None),'a')
        self.assertEqual(select_event(events,NOW,'b'),'b')
