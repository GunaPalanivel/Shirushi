"""Acquisition failures, real contract shapes and independently audited facts."""
import copy
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.api_sources import ACCOUNTS, ENTITY, check_api, propose_api
from shirushi.contracts import ROOT, load, validate_envelopes
from shirushi.fetch import Budget, BudgetExceeded, Fetcher, SourceUnavailable, public_addresses, safe_url
from shirushi.live import unique_decisions, worker
from shirushi.refresh import merge
from shirushi.showcase import render
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.score import failure_stage
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'
WHEN = '2026-10-08T08:00:00Z'


def account(year=2025, scope='SELSKAP', amount=0, subject=SUBJECT):
    return {'id': year, 'regnskapstype': scope, 'virksomhet': {'organisasjonsnummer': subject},
            'valuta': 'NOK', 'regnskapsperiode': {'fraDato': f'{year}-01-01', 'tilDato': f'{year}-12-31'},
            'resultatregnskapResultat': {'driftsresultat': {'driftsinntekter': {'sumDriftsinntekter': amount}}}}


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT / 'configs/local-live.json')
        self.config.update(min_host_interval_seconds=0, max_retries=0)
        self.budget = Budget(self.config, time.monotonic() + 30)

    def test_refuses_credentials_ports_and_local_or_mixed_dns(self):
        for url in ('http://data.brreg.no/', 'https://user:secret@data.brreg.no/',
                    'https://data.brreg.no:8443/', 'https://data.brreg.no/\r\nX:secret'):
            with self.assertRaises(SourceUnavailable):
                safe_url(url)
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 443)),
                                                      (None, None, None, None, ('8.8.8.8', 443))]):
            with self.assertRaises(SourceUnavailable):
                public_addresses('example.com')

    def test_failed_attempts_and_retry_are_charged(self):
        self.config['max_retries'] = 1
        fetcher = Fetcher(self.budget, transport=lambda *args: (_ for _ in ()).throw(OSError('offline')))
        with self.assertRaises(SourceUnavailable):
            fetcher.get(ENTITY + SUBJECT, {'data.brreg.no'})
        self.assertEqual(self.budget.requests, 2)

    def test_redirect_cannot_escape_scope(self):
        fetcher = Fetcher(self.budget, transport=lambda *a: (302, {'location': 'https://127.0.0.1/private'}, b''))
        with self.assertRaises(SourceUnavailable):
            fetcher.get(ENTITY + SUBJECT, {'data.brreg.no'})
        self.assertEqual(self.budget.requests, 1)

    def test_robots_refusal_stops_page_fetch(self):
        fetcher = Fetcher(self.budget, transport=lambda *a: (200, {}, b'User-agent: *\nDisallow: /\n'))
        with self.assertRaisesRegex(SourceUnavailable, 'Robots disallows'):
            fetcher.get('https://example.com/', {'example.com'}, robots=True)
        self.assertEqual(self.budget.requests, 1)

    def test_budget_stops_before_another_request(self):
        self.config['request_budget'] = 1
        fetcher = Fetcher(self.budget, transport=lambda *a: (200, {}, b'{}'))
        fetcher.get(ENTITY + SUBJECT, {'data.brreg.no'})
        with self.assertRaises(BudgetExceeded):
            fetcher.get(ACCOUNTS + SUBJECT, {'data.brreg.no'})
        self.assertEqual(self.budget.requests, 1)
        self.assertEqual(self.budget.bytes, 2)

    def test_body_and_total_byte_bounds(self):
        self.config['max_response_bytes'] = 2
        with self.assertRaises(SourceUnavailable):
            Fetcher(self.budget, lambda *a: (200, {}, b'123')).get(ENTITY + SUBJECT, {'data.brreg.no'})
        self.config['max_total_bytes'] = 3
        with self.assertRaises(BudgetExceeded):
            Fetcher(self.budget, lambda *a: (200, {}, b'1')).get(ENTITY + SUBJECT, {'data.brreg.no'})


class LiveSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / 'store')

    def save(self, body, kind='brreg_accounts'):
        raw = json.dumps(body, ensure_ascii=False).encode()
        url = (ACCOUNTS if kind == 'brreg_accounts' else ENTITY) + SUBJECT
        return self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': kind,
                                    'source_url': url, 'effective_url': url, 'http_status': 200,
                                    'retrieved_at': WHEN, 'sha256': digest(raw), 'source_origin': 'data.brreg.no',
                                    'access_policy': 'brreg-open-data-nlod-2.0'})

    def decisions(self, body):
        sid = self.save(body)
        return [check_api(self.store, c, SUBJECT) for c in propose_api(self.store, sid)]

    def test_years_and_entity_group_scopes_survive_refresh(self):
        original = self.decisions([account(2024), account(), account(scope='KONSERN')])
        first = merge(None, original, WHEN)
        second = merge(first, self.decisions([account(2024), account(amount=5), account(scope='KONSERN')]), WHEN)
        self.assertEqual(len(second['claims']), 3)
        self.assertEqual(len(second['changes']), 1)
        self.assertEqual(second['changes'][0]['old_value']['amount'], 0)
        self.assertEqual(second['changes'][0]['new_value']['amount'], 5)
        unchanged = merge(second, self.decisions([account(2024), account(amount=5), account(scope='KONSERN')]), WHEN)
        self.assertEqual(unchanged['changes'], [])
        self.assertEqual(len(unchanged['evidence']), len(second['evidence']))

    def test_wrong_company_and_boolean_money_are_rejected(self):
        for body in ([account(subject='999999999')], [account(amount=True)]):
            self.assertFalse(self.decisions(body)[0]['accepted'])

    def test_conflicting_same_period_abstains(self):
        result = unique_decisions(self.decisions([account(amount=1), account(amount=2)]))
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['accepted'])
        self.assertEqual(result[0]['availability'], 'ambiguous')

    def test_independent_audit_catches_period_scope_and_amount_tampering(self):
        decision = self.decisions([account(amount=5)])[0]
        auditor = SourceAudit(self.store.root, [SUBJECT])
        claim, evidence = decision['claim'], {decision['evidence']['id']: decision['evidence']}
        with patch('shirushi.api_sources.check_api', side_effect=AssertionError('Maker checker called')):
            auditor.claim(SUBJECT, claim, evidence)
            for key, wrong in [('amount', 5000), ('account_scope', 'group'), ('period', {'fraDato': '2024-01-01', 'tilDato': '2024-12-31'})]:
                damaged = copy.deepcopy(claim)
                damaged['value'][key] = wrong
                with self.assertRaises(ValueError):
                    auditor.claim(SUBJECT, damaged, evidence)

    def test_failed_refresh_preserves_supported_slot(self):
        first = merge(None, self.decisions([account()]), WHEN)
        claim = first['claims'][0]
        second = merge(first, [{'field': claim['field'], 'claim_id': claim['claim_id'],
                               'accepted': False, 'reason': 'HTTP 503'}], WHEN)
        self.assertEqual(second['claims'][0]['value'], claim['value'])
        self.assertEqual(second['claims'][0]['freshness'], 'stale_after_failed_observation')
        self.assertEqual(second['changes'], [])

    def test_web_jsonld_requires_exact_employer(self):
        anchor = self.save({'organisasjonsnummer': SUBJECT, 'hjemmeside': 'https://example.com'}, 'brreg_entity')
        for identity, expected in [(SUBJECT, 1), ('999999999', 0)]:
            body = {'@type': 'JobPosting', 'title': 'Engineer', 'datePosted': '2026-10-01',
                    'validThrough': '2099-01-01', 'identifier': 'vacancy-42',
                    'hiringOrganization': {'identifier': identity}}
            raw = ('<script type="application/ld+json">' + json.dumps(body) + '</script>').encode()
            sid = self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': 'company_owned',
                                       'source_url': 'https://example.com/jobs', 'effective_url': 'https://example.com/jobs',
                                       'retrieved_at': WHEN, 'http_status': 200, 'sha256': digest(raw),
                                       'source_origin': 'example.com', 'declared_host': 'example.com', 'robots_checked': True,
                                       'ownership_anchor_snapshot_id': anchor})
            decisions = check_web(self.store, SUBJECT, sid)
            self.assertEqual(len(decisions), expected)
            if decisions:
                SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, decisions[0]['claim'],
                                                          {decisions[0]['evidence']['id']: decisions[0]['evidence']})

    def test_showcase_escapes_claim_text(self):
        decision = self.decisions([account()])[0]
        envelope = dict(merge(None, [decision], WHEN), organisation_number=SUBJECT, opportunities=[])
        envelope['claims'][0]['value'] = '<script>alert(1)</script>'
        render([envelope], Path(self.temp.name) / 'site')
        page = (Path(self.temp.name) / 'site/signalpost' / (SUBJECT + '.html')).read_text()
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_source_failures_classified_by_actual_family(self):
        gold = {'family': 'business_products', 'field': 'business_description', 'value': 'Energy'}
        stage, _ = failure_stage({}, {'attempts': [{'source': 'company_owned', 'status': 'checked'}]}, gold)
        self.assertEqual(stage, 'extraction')

    def run_worker(self, request_budget=100, previous=None, declared_website=None):
        config = load(ROOT / 'configs/local-live.json')
        config.update(min_host_interval_seconds=0, request_budget=request_budget,
                      enabled_sources=['brreg_entity', 'brreg_roles', 'brreg_accounts', 'brreg_subunits'])
        subjects = [SUBJECT, '989061593']
        frames = []
        class Connection:
            def send(self, message):
                frames.append(message)
            def close(self):
                pass
        def fake_get(fetcher, url, hosts, robots=False):
            fetcher.budget.start('data.brreg.no')
            subject = re.search('[0-9]{9}', url).group()
            if '/regnskap/' in url:
                body = [account(subject=subject)]
            elif '/roller' in url:
                body = {'rollegrupper': []}
            elif '/underenheter' in url:
                body = {'_embedded': {'underenheter': []}}
            else:
                body = {'organisasjonsnummer': subject, '_links': {'self': {'href': url}},
                        'navn': 'Synthetic company', 'aktivitet': ['Synthetic registered activity']}
                if declared_website:
                    body['hjemmeside'] = declared_website
            raw = json.dumps(body).encode()
            fetcher.budget.consume(len(raw))
            return raw, {'source_url': url, 'effective_url': url, 'http_status': 200,
                         'retrieved_at': WHEN, 'source_origin': 'data.brreg.no', 'content_type': 'application/json'}
        job = {'store': self.store.root, 'subjects': subjects, 'previous': previous or {}, 'config': config,
               'deadline': time.monotonic() + 30, 'started_at': WHEN, 'run_id': 'synthetic-live'}
        with patch('shirushi.fetch.Fetcher.get', fake_get):
            worker(Connection(), job)
        fatal = [f for f in frames if f[0] == 'fatal']
        self.assertEqual(fatal, [])
        output = [f[2]['envelope'] for f in frames if f[0] == 'result']
        errors = validate_envelopes([{'organisation_number': s} for s in subjects], output,
                                    load(ROOT / 'contracts/company-envelope.v1.json'))
        self.assertEqual(errors, [])
        return output, frames

    def test_registry_website_lead_keeps_owned_page_coverage_unknown(self):
        output, _ = self.run_worker(declared_website='https://example.com/')
        for row in output:
            self.assertTrue(any(c['field'] == 'declared_website' and c['availability'] == 'available'
                                for c in row['claims']))
            opportunity = next(o for o in row['opportunities'] if o['family'] == 'website_owned_profiles')
            self.assertEqual(opportunity['status'], 'unknown')
            self.assertTrue(any(c['field'] == 'coverage:website_owned_profiles' for c in row['claims']))

    def test_live_budget_failure_preserves_checked_facts_and_all_outputs(self):
        output, frames = self.run_worker(request_budget=3)
        self.assertEqual(len(output), 2)
        self.assertTrue(all(e['run']['terminal_status'] == 'failed' for e in output))
        self.assertTrue(all(any(c['field'] == 'legal_name' and c['availability'] == 'available'
                                for c in e['claims']) for e in output))
        self.assertEqual([f[2]['requests'] for f in frames if f[0] == 'accounting'][-1], 3)

    def test_live_refresh_keeps_unknown_slots_unique_and_is_idempotent(self):
        first, _ = self.run_worker()
        second, _ = self.run_worker(previous={e['organisation_number']: e for e in first})
        self.assertTrue(all(not e['changes'] for e in second))
        self.assertEqual([len(e['claims']) for e in first], [len(e['claims']) for e in second])

if __name__ == '__main__':
    unittest.main()
