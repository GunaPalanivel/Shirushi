"""Legal context, NAV attribution, currentness and sampling regressions."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.contracts import ROOT, load, validate_envelopes
from shirushi.discovery import AnySearchDiscovery
from shirushi.fetch import Budget, Fetcher, SourceUnavailable
from shirushi.live import acquire_website, worker
from shirushi.nav_jobs import HOST, SUBUNIT, NavFeed, check_nav
from shirushi.refresh import merge
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit
from tools.prepare_development_corpus import sample

SUBJECT, EMPLOYER = '942037538', '971802928'
UUID = '5cfc8fff-7fb3-47f4-891e-4a4b015a9166'
WHEN = '2026-10-08T08:00:00Z'
JOB_URL = 'https://' + HOST + '/api/v1/feedentry/' + UUID


class CoverageRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))

    def save(self, body, url, kind, **extra):
        raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body.encode()
        return self.store.save(raw, dict(organisation_number=SUBJECT, source_class=kind,
            source_url=url, effective_url=url, http_status=200, retrieved_at=WHEN,
            sha256=digest(raw), source_origin=url.split('/')[2], **extra))

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [SUBJECT])
        with patch('shirushi.nav_jobs.check_nav', side_effect=AssertionError('Maker called by audit')):
            for d in decisions:
                audit.claim(SUBJECT, d['claim'], {d['evidence']['id']: d['evidence']})

    def nav(self, parent=SUBJECT, **extra):
        anchor = self.save({'organisasjonsnummer': SUBJECT, 'navn': 'Company AS'},
                          'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, 'brreg_entity')
        bridge = self.save({'organisasjonsnummer': EMPLOYER, 'overordnetEnhet': parent},
                           SUBUNIT + EMPLOYER, 'brreg_job_employer')
        ad = dict(uuid=UUID, title='Vehicle painter', published='2026-10-07T13:14:17+02:00',
                  expires='2026-11-02T00:00:00+01:00', description='Unattributed client job duties',
                  employer={'orgnr': EMPLOYER, 'description': 'Company repairs and paints vehicles.'})
        ad.update(extra)
        sid = self.save({'uuid': UUID, 'status': 'ACTIVE', 'ad_content': ad}, JOB_URL,
                        'nav_jobs', employer_snapshot_id=bridge, legal_identity_snapshot_id=anchor)
        return check_nav(self.store, SUBJECT, sid)

    def test_nav_actual_schema_and_subunit_bridge_cover_two_families(self):
        decisions = self.nav()
        self.assertEqual({d['family'] for d in decisions}, {'business_products', 'jobs_dated_activity'})
        self.assertEqual(next(d['claim']['value'] for d in decisions if d['field'] == 'business_description'),
                         'Company repairs and paints vehicles.')
        self.audit(decisions)

    def test_nav_different_legal_parent_never_publishes(self):
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            self.nav(parent='999999999')

    def test_nav_expired_future_or_empty_titles_never_count(self):
        for change in [{'expires': '2026-10-01T00:00:00Z'}, {'published': '2099-01-01T00:00:00Z'}, {'title': ' '}]:
            self.assertEqual(self.nav(**change), [])

    def test_nav_job_description_is_not_company_description(self):
        decisions = self.nav(employer={'orgnr': EMPLOYER, 'description': ''})
        self.assertEqual([d['field'] for d in decisions], ['job_posting'])
        self.audit(decisions)

    def test_nav_parent_customer_recruitment_and_negation_do_not_cover_business(self):
        for text in ['Parent ASA produces timber.', 'Company is a customer of Vendor AS which produces valves.',
                     'Company does not produce pumps.', 'Painter wanted by Company AS, 60 percent position.',
                     'Company is a private firm located in Askim.',
                     '<script>Company produces paints.</script>']:
            decisions = self.nav(employer={'orgnr': EMPLOYER, 'description': text})
            self.assertEqual([d['field'] for d in decisions], ['job_posting'])
            self.audit(decisions)

    def test_nav_independent_audit_rejects_value_date_family_and_locator_forgery(self):
        decision = self.nav()[0]
        for target, key, value in [('claim', 'family', 'business_products'),
                                   ('claim', 'item_key', 'wrong'), ('evidence', 'locator', {'path': ['ad_content', 'description']})]:
            bad = copy.deepcopy(decision); bad[target][key] = value
            with self.assertRaises(ValueError): self.audit([bad])
        bad = copy.deepcopy(decision); bad['claim']['value']['valid_through'] = '2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError): self.audit([bad])

    def test_job_without_current_support_moves_to_history(self):
        first = merge(None, self.nav(), WHEN)
        job = next(c for c in first['claims'] if c['field'] == 'job_posting')
        second = merge(first, [{'field': 'job_posting', 'claim_id': job['claim_id'], 'accepted': False,
            'withdrawn': True, 'reason': 'current_active_posting_not_verified'}], WHEN)
        self.assertIsNone(next(c for c in second['claims'] if c['field'] == 'job_posting')['value'])
        self.assertEqual(second['history'], [job])
        from shirushi.showcase import profile
        second.update(organisation_number=SUBJECT, opportunities=[])
        self.assertNotIn('Vehicle painter', profile(second))

    def test_seller_contract_allows_scoped_literal_catalogue_not_other_locale(self):
        anchor = self.save({'organisasjonsnummer': SUBJECT, 'navn': 'Example AS'},
                          'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, 'brreg_entity')
        def page(raw, path, **extra):
            return self.save(raw, 'https://example.com' + path, 'company_owned', declared_host='example.com',
                robots_checked=True, ownership_anchor_snapshot_id=anchor, **extra)
        owner = page('<p>Terms for purchase agreements between Example AS, organization no. 942037538 and customers.</p>',
                     '/nb-no/terms')
        decisions = check_web(self.store, SUBJECT, owner)
        self.assertEqual(decisions[0]['claim']['value'], 'https://example.com/nb-no/')
        self.audit(decisions)
        child = page('<a href="/nb-no/products/work-jacket">Work jacket</a>'
                     '<a href="/sv-se/products/foreign-jacket">Foreign jacket</a>', '/nb-no/', operator_snapshot_id=owner)
        decisions = check_web(self.store, SUBJECT, child)
        self.assertEqual([d['claim']['value']['name'] for d in decisions], ['Work jacket'])
        self.audit(decisions)
        foreign = page('<a href="/sv-se/products/work-jacket">Work jacket</a>', '/sv-se/', operator_snapshot_id=owner)
        with self.assertRaisesRegex(ValueError, 'escapes'): check_web(self.store, SUBJECT, foreign)

    def test_same_org_in_customer_terms_does_not_verify_seller(self):
        from shirushi.html_sources import operator_proof
        self.assertIsNone(operator_proof(b'<p>Terms for purchase agreements between Vendor AS and customer Example AS, organization no. 942037538.</p>', SUBJECT, 'Example AS'))
        self.assertIsNone(operator_proof(b'<p>Terms for purchase agreements between Example AS, organization no. 942037538, as customer and seller Vendor AS.</p>', SUBJECT, 'Example AS'))
        self.assertIsNone(operator_proof(b'<footer>Copyright Directory AS. Customer Example AS, org.nr. 942037538.</footer>', SUBJECT, 'Example AS'))

    def test_discovery_checks_legal_page_before_catalogue_and_audits_full_worker(self):
        config = load(ROOT / 'configs/local-external.json')
        config.update(enabled_sources=['brreg_entity', 'company_owned'], min_host_interval_seconds=0, max_retries=0)
        frames, seen = [], []
        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass
        def transport(fetcher, url, timeout, limit, headers=None, request_body=None):
            seen.append(url)
            if 'api.anysearch.com' in url:
                raw = json.dumps({'code': 0, 'data': {'results': [{'url': 'https://example.com/nb-no/'}]}}).encode()
                kind = 'application/json'
            elif 'data.brreg.no' in url:
                raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': 'Example AS', '_links': {'self': {'href': url}}}).encode()
                kind = 'application/json'
            elif url.endswith('robots.txt'):
                raw, kind = b'User-agent: *\nAllow: /', 'text/plain'
            elif url.endswith('/terms'):
                raw, kind = b'<p>Terms for purchase agreements between Example AS, organization no. 942037538 and customers.</p>', 'text/html'
            else:
                raw, kind = b'<a href="/nb-no/terms">Terms</a><a href="/nb-no/products/work-jacket">Work jacket</a>', 'text/html'
            fetcher.budget.consume(len(raw))
            return 200, {'content-type': kind}, raw
        job = {'store': self.store.root, 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 5, 'started_at': WHEN, 'run_id': 'legal-traversal',
               'discovery': {'provider': 'anysearch', 'max_queries_per_company': 2, 'max_candidates': 3, 'request_interval_seconds': .02}}
        with patch('shirushi.fetch.Fetcher._request', transport): worker(Connection(), job)
        self.assertFalse([f for f in frames if f[0] == 'fatal'])
        result = next(f[2]['envelope'] for f in frames if f[0] == 'result')
        self.assertEqual({o['family'] for o in result['opportunities'] if o['status'] == 'covered'},
                         {'business_products', 'website_owned_profiles'})
        self.assertLess(seen.index('https://example.com/nb-no/terms'), seen.index('https://example.com/nb-no/products/work-jacket'))
        audit = SourceAudit(self.store.root, [SUBJECT]); evidence = {e['id']: e for e in result['evidence']}
        for c in result['claims']: audit.claim(SUBJECT, c, evidence)

    def test_sitemap_recovers_unlinked_seller_terms_after_empty_exact_search(self):
        config = load(ROOT / 'configs/local-external.json')
        config.update(enabled_sources=['brreg_entity', 'company_owned'], min_host_interval_seconds=0, max_retries=0,
                      max_pages_per_company=6)
        frames, seen = [], []
        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass
        def transport(fetcher, url, timeout, limit, headers=None, request_body=None):
            seen.append(url)
            if 'api.anysearch.com' in url:
                mode = getattr(self, '_search_mode', 'empty_exact')
                if mode == 'quota':
                    return 402, {'content-type': 'application/json'}, b'{"code":-1,"message":"sensitive-provider-message"}'
                if mode == 'malformed':
                    return 200, {'content-type': 'application/json'}, b'{"code":0,"data":null}'
                if mode == 'noisy':
                    return 200, {'content-type': 'application/json'}, json.dumps({'code': 0, 'data': {'results': [
                        {'url': 'https://newsroom.example.com/press'}, {'url': 'https://reseller.test/product'}]}}).encode()
                query = json.loads(request_body)['query']
                results = [] if '942 037 538' in query else [{'url': 'https://example.com/fr/contact'}]
                raw, kind = json.dumps({'code': 0, 'data': {'results': results}}).encode(), 'application/json'
            elif 'data.brreg.no' in url:
                raw, kind = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': 'Example AS', '_links': {'self': {'href': url}}}).encode(), 'application/json'
            elif url.endswith('robots.txt'):
                raw, kind = b'User-agent: *\nAllow: /\nSitemap: https://example.com/index.xml', 'text/plain'
            elif url.endswith('/index.xml'):
                raw, kind = b'<sitemapindex><sitemap><loc>https://example.com/fr/map.xml</loc></sitemap><sitemap><loc>https://example.com/nb-no/map.xml</loc></sitemap></sitemapindex>', 'application/xml'
            elif url.endswith('/nb-no/map.xml'):
                raw, kind = b'<urlset><url><loc>https://other.example/nb-no/terms</loc></url><url><loc>https://example.com/nb-no/terms</loc></url></urlset>', 'application/xml'
            elif url.endswith('/terms'):
                raw, kind = b'<p>Terms for purchase agreements between Example AS, organization no. 942037538 and customers.</p>', 'text/html'
            elif url.endswith('/fr/contact') or url in ('https://example.com/', 'https://example.no/'):
                raw, kind = b'<a data-language="NB-NO" href="/nb-no/">Norsk</a>', 'text/html'
            else:
                raw, kind = b'<a href="/nb-no/legal-notice">Legal</a><a href="/nb-no/om-oss/jobs">Careers</a><a href="/nb-no/products/work-jacket">Work jacket</a>', 'text/html'
            if kind == 'text/html' and getattr(self, '_search_mode', None) == 'boolean_attributes':
                raw = b'<i title></i><link hreflang href="/wrong"><script type></script>' + raw
            fetcher.budget.consume(len(raw))
            return 200, {'content-type': kind}, raw
        job = {'store': self.store.root, 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 5, 'started_at': WHEN, 'run_id': 'sitemap-traversal',
               'discovery': {'provider': 'anysearch', 'max_queries_per_company': 2, 'max_candidates': 3, 'request_interval_seconds': .02}}
        if getattr(self, '_search_mode', None) == 'no_provider':
            job['discovery'] = None
        with patch('shirushi.fetch.Fetcher._request', transport): worker(Connection(), job)
        self.assertFalse([f for f in frames if f[0] == 'fatal'])
        result = next(f[2]['envelope'] for f in frames if f[0] == 'result')
        self.assertEqual({o['family'] for o in result['opportunities'] if o['status'] == 'covered'},
                         {'business_products', 'website_owned_profiles'})
        self.assertEqual([u for u in seen if u.endswith('.xml')],
                         ['https://example.com/index.xml', 'https://example.com/nb-no/map.xml'])
        self.assertFalse([u for u in seen if 'other.example' in u])
        pages = [u for u in seen if 'example.com' in u and not u.endswith(('.xml', 'robots.txt'))]
        self.assertLessEqual(len(pages), 6)
        audit = SourceAudit(self.store.root, [SUBJECT]); evidence = {e['id']: e for e in result['evidence']}
        for claim in result['claims']: audit.claim(SUBJECT, claim, evidence)
        requests = next(f[2]['requests'] for f in reversed(frames) if f[0] == 'accounting')
        self.assertEqual(requests, len(seen))
        self.assertNotIn('sensitive-provider-message', json.dumps(frames))
        if getattr(self, '_search_mode', None) == 'no_provider':
            self.assertFalse([u for u in seen if 'api.anysearch.com' in u])

    def test_worker_keeps_verified_outputs_with_quota_malformed_or_no_provider(self):
        for mode in ('quota', 'malformed', 'no_provider', 'noisy', 'boolean_attributes'):
            with self.subTest(mode=mode):
                self._search_mode = mode
                self.test_sitemap_recovers_unlinked_seller_terms_after_empty_exact_search()

    def test_boolean_html_attributes_do_not_terminate_locale_parsing(self):
        from shirushi.web_sources import Page, locale_links
        raw = b'<a title href="/contact">Contact</a><link hreflang href="/empty"><script type>skip</script><a hreflang data-language="NB-NO" href="/nb-no/">Norsk</a>'
        self.assertEqual(locale_links(raw, 'https://example.com/'), ['https://example.com/nb-no/'])
        self.assertEqual(Page(raw).scripts, [])

    def test_nav_shared_window_reaches_a_later_page_and_retains_truncation(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(max_retries=0, min_host_interval_seconds=0)
        def transport(url, timeout, limit, headers=None):
            if url.endswith('/publicToken'):
                return 200, {}, b'aaa.bbb.ccc'
            page = 2 if url.endswith('?p=2') else 3 if url.endswith('?p=3') else 1
            name = ['Other AS', 'Another AS', 'Example AS'][page - 1]
            body = {'items': [{'url': '/api/v1/feedentry/' + UUID,
                     '_feed_entry': {'status': 'ACTIVE', 'businessName': name}}],
                    'next_url': '/api/v1/feed?p=' + str(page + 1) if page < 3 else None}
            return 200, {}, json.dumps(body).encode()
        limited = NavFeed(Fetcher(Budget(config, time.monotonic() + 3), transport), max_pages=2)
        self.assertNotIn('example', limited.headers())
        self.assertFalse(limited.diagnostics['window_complete'])
        budget = Budget(config, time.monotonic() + 3)
        wider = NavFeed(Fetcher(budget, transport))
        self.assertEqual(wider.headers()['example'], [JOB_URL])
        self.assertTrue(wider.diagnostics['window_complete'])
        wider.headers()
        self.assertEqual(budget.requests, 4)

    def test_malformed_search_is_a_source_failure_and_quota_is_single_flight(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(max_retries=0, min_host_interval_seconds=0)
        receipt = {'request_interval_seconds': .02, 'max_queries_per_company': 2, 'max_candidates': 3}
        for value in (None, {'code': 0, 'data': None}, {'code': 0, 'data': []}, {'code': 0, 'data': {'results': None}}):
            with self.subTest(value=value):
                budget = Budget(config, time.monotonic() + 3)
                search = AnySearchDiscovery(Fetcher(budget, lambda *a: (200, {}, json.dumps(value).encode())), receipt)
                with self.assertRaisesRegex(SourceUnavailable, 'Invalid discovery response'):
                    search.candidates(SUBJECT)
        budget = Budget(config, time.monotonic() + 3)
        search = AnySearchDiscovery(Fetcher(budget, lambda *a: (402, {}, b'sensitive-provider-message')), receipt)
        self.assertEqual(search.candidates(SUBJECT, {'navn': 'Example AS'}), ['https://example.com/', 'https://example.no/'])
        self.assertEqual(search.candidates(EMPLOYER, {'navn': 'Another AS'}), ['https://another.com/', 'https://another.no/'])
        self.assertEqual(budget.requests, 1)
        self.assertNotIn('sensitive-provider-message', json.dumps(search.diagnostics))

    def test_sitemap_rejects_entities_unsafe_hosts_and_wrong_locale(self):
        from shirushi.web_sources import sitemap_links
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            sitemap_links(b'<!DOCTYPE x [<!ENTITY x "boom">]><urlset/>', 'https://example.com/map.xml', '/nb-no/')
        raw = b'<urlset><url><loc>https://example.com/fr/terms</loc></url><url><loc>https://example.com/nb-no/legal</loc></url><url><loc>http://example.com/nb-no/terms</loc></url><url><loc>https://user:pass@example.com/nb-no/terms</loc></url><url><loc>https://other.example/nb-no/terms</loc></url><url><loc>https://example.com/nb-no/terms</loc></url></urlset>'
        kind, leads = sitemap_links(raw, 'https://example.com/map.xml', '/nb-no/')
        self.assertEqual(kind, 'urlset')
        self.assertEqual(leads, ['https://example.com/nb-no/terms', 'https://example.com/nb-no/legal'])

    def test_anonymous_quota_failure_is_not_retried_for_every_company(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(max_retries=0)
        budget = Budget(config, time.monotonic() + 3)
        search = AnySearchDiscovery(Fetcher(budget, lambda *args: (429, {}, b'')),
            {'request_interval_seconds': .02, 'max_queries_per_company': 2, 'max_candidates': 3})
        reasons = []
        for _ in range(100):
            with self.assertRaises(SourceUnavailable): search.candidates(SUBJECT)
            reasons.append(search.diagnostics[SUBJECT][-1]['reason'])
        self.assertEqual(budget.requests, 1)
        self.assertEqual(len(set(reasons[1:])), 1)
        self.assertEqual(reasons[-1].count('Anonymous discovery unavailable:'), 1)
        self.assertEqual(search.error, reasons[-1])

    def test_bootstrap_failure_is_shared_instead_of_repeated_for_each_company(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(min_host_interval_seconds=0, max_retries=0)
        budget = Budget(config, time.monotonic() + 3)
        nav = NavFeed(Fetcher(budget, lambda *args: (403, {}, b'')))
        reasons = []
        for _ in range(100):
            with self.assertRaises(SourceUnavailable) as failure:
                nav.headers()
            reasons.append(str(failure.exception))
        self.assertEqual(budget.requests, 1)
        self.assertEqual(len(set(reasons)), 1)
        self.assertEqual(reasons[0].count('NAV feed bootstrap unavailable:'), 1)

    def test_nav_timeout_identifies_bootstrap_stage_and_does_not_retry_per_company(self):
        for stage in ('public_token', 'feed_page'):
            with self.subTest(stage=stage):
                config = load(ROOT / 'configs/local-live.json')
                config.update(min_host_interval_seconds=0, max_retries=1)
                budget = Budget(config, time.monotonic() + 3)
                def transport(url, *args):
                    if stage == 'feed_page' and url.endswith('/publicToken'):
                        return 200, {}, b'header.payload.signature'
                    raise TimeoutError('The read operation timed out')
                nav = NavFeed(Fetcher(budget, transport))
                reasons = []
                for _ in range(100):
                    with self.assertRaises(SourceUnavailable) as failure:
                        nav.headers()
                    reasons.append(str(failure.exception))
                self.assertEqual(budget.requests, 2 if stage == 'public_token' else 3)
                self.assertEqual(nav.diagnostics['bootstrap_stage'], stage)
                self.assertEqual(nav.diagnostics['pages'], 0)
                self.assertEqual(len(set(reasons)), 1)
                self.assertIsNone(nav.index)

    def test_worker_reports_nav_stage_when_acquisition_fails(self):
        config = load(ROOT / 'configs/local-live.json')
        config.update(enabled_sources=['brreg_entity', 'nav_jobs'], min_host_interval_seconds=0, max_retries=1)
        frames = []
        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass
        def transport(fetcher, url, *args):
            if 'data.brreg.no' in url:
                raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': 'Company AS',
                                  '_links': {'self': {'href': url}}}).encode()
                fetcher.budget.consume(len(raw))
                return 200, {'content-type': 'application/json'}, raw
            raise TimeoutError('The read operation timed out')
        job = {'store': self.store.root, 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 3, 'started_at': WHEN, 'run_id': 'nav-timeout'}
        with patch('shirushi.fetch.Fetcher._request', transport):
            worker(Connection(), job)
        result = next(frame[2] for frame in frames if frame[0] == 'result')
        nav = next(attempt for attempt in result['attempts'] if attempt['source'] == 'nav_jobs')
        self.assertEqual(nav['feed_window']['bootstrap_stage'], 'public_token')
        self.assertEqual(nav['status'], 'failed')
        self.assertEqual(nav['requests'], 2)
        self.assertEqual(result['envelope']['run']['terminal_status'], 'completed')

    def test_nav_and_post_credentials_cannot_escape_scoped_endpoints(self):
        config = load(ROOT / 'configs/local-live.json'); budget = Budget(config, time.monotonic() + 3)
        fetcher = Fetcher(budget)
        for url in ['https://example.com/api/v1/feed', 'https://' + HOST + '/api/publicToken']:
            with self.assertRaises(SourceUnavailable): fetcher.get(url, {url.split('/')[2]}, request_headers={'Authorization': 'Bearer secret'})
        with self.assertRaises(SourceUnavailable): fetcher.get('https://example.com/v1/search', {'example.com'}, request_body=b'{}')
        self.assertEqual(budget.requests, 0)

    def test_international_path_and_query_are_encoded_at_http_boundary(self):
        from unittest.mock import MagicMock
        config = load(ROOT / 'configs/local-live.json')
        fetcher = Fetcher(Budget(config, time.monotonic() + 3))
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.isclosed.return_value = True
        response.status = 200; response.getheaders.return_value = []
        with patch('shirushi.fetch.public_addresses', return_value=['8.8.8.8']), \
                patch('shirushi.fetch.PinnedHTTPS', return_value=connection):
            fetcher._request('https://example.com/tjenester/r\u00f8r?q=bl\u00e5%20pumpe', 1, 1024)
        self.assertEqual(connection.request.call_args.args[1], '/tjenester/r%C3%B8r?q=bl%C3%A5%20pumpe')

    def test_anysearch_uses_name_and_exact_org_and_prefers_legal_page(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(min_host_interval_seconds=0, max_retries=0)
        budget = Budget(config, time.monotonic() + 3); calls = []
        def transport(url, timeout, limit, headers, body):
            calls.append(json.loads(body))
            candidate = 'https://example.com/' if len(calls) == 1 else 'https://example.com/nb-no/terms'
            return 200, {}, json.dumps({'code': 0, 'data': {'results': [{'url': candidate}, {'url': 'https://proff.no/directory'}]}}).encode()
        search = AnySearchDiscovery(Fetcher(budget, transport), {'request_interval_seconds': .02, 'max_queries_per_company': 2, 'max_candidates': 3})
        self.assertEqual(search.candidates(SUBJECT, {'navn': 'Example AS'})[0], 'https://example.com/nb-no/terms')
        self.assertIn('Example AS', calls[0]['query'])
        self.assertIn('942 037 538', calls[0]['query'])
        self.assertEqual(calls[1]['query'], 'site:example.com "942 037 538"')
        self.assertEqual(search.diagnostics[SUBJECT][1]['candidate_urls'],
                         ['https://example.com/nb-no/terms', 'https://proff.no/directory'])

    def test_discovery_foreign_locale_is_a_lead_not_ownership(self):
        config = load(ROOT / 'configs/local-live.json'); config.update(min_host_interval_seconds=0, max_retries=0)
        budget = Budget(config, time.monotonic() + 3); calls = []
        def transport(url, timeout, limit, headers, body):
            calls.append(json.loads(body)['query'])
            urls = (['https://example.com/fr-ch/contact', 'https://newsroom.example.com/press',
                     'https://reseller.no/product'] if len(calls) == 1 else ['https://example.com/nb-no/terms'])
            return 200, {}, json.dumps({'code': 0, 'data': {'results': [{'url': u} for u in urls]}}).encode()
        search = AnySearchDiscovery(Fetcher(budget, transport), {'request_interval_seconds': .02,
            'max_queries_per_company': 2, 'max_candidates': 3})
        self.assertEqual(search.candidates(SUBJECT, {'navn': 'Example AS'})[0], 'https://example.com/nb-no/terms')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], 'site:example.com "942 037 538"')

    def test_non_html_candidate_does_not_abort_later_ownership_check(self):
        class Discovery:
            def candidates(self, subject, entity):
                return ['https://files.example.no/report', 'https://example.no/terms']
        class Pages:
            def get(self, url, hosts, robots=False):
                if 'files.' in url:
                    return b'%PDF-1.7', {'content_type': 'application/pdf', 'effective_url': url}
                if url.endswith('/terms'):
                    raw = ('<p>These terms govern purchases between Example AS and its customers. '
                           'Organisation number 942 037 538.</p>').encode()
                else:
                    raw = b'<p>No offers.</p>'
                return raw, {'content_type': 'text/html; charset=utf-8', 'effective_url': url}
        pages, failures, funnel = acquire_website(Pages(), SUBJECT, {'navn': 'Example AS'}, Discovery(), 3)
        self.assertEqual(pages[0][1]['effective_url'], 'https://example.no/terms')
        self.assertIn('not HTML', failures[0]['reason'])
        self.assertEqual(funnel['candidate_identity_rejections'], 0)

    def test_linked_norwegian_locale_reaches_legal_seller_before_foreign_terms(self):
        from shirushi.web_sources import locale_links
        seen = []
        foreign = ('<a data-language="NB-NO" href="/nb-no/">Norway</a>'
                   '<a href="/fr-ch/terms">Terms</a>'
                   '<link hreflang="nb-NO" href="https://other.no/">').encode()
        self.assertEqual(locale_links(foreign, 'https://example.com/fr-ch/contact'), ['https://example.com/nb-no/'])
        class Discovery:
            def candidates(self, subject, entity): return ['https://example.com/fr-ch/contact']
        class Pages:
            def get(self, url, hosts, robots=False):
                seen.append(url)
                if '/fr-ch/' in url: raw = foreign
                elif url.endswith('/terms'):
                    raw = b'<p>Terms for purchases between Example AS, org.nr. 942037538 and customers.</p>'
                else:
                    raw = b'<a href="/nb-no/terms">Terms</a><a href="/nb-no/products/jacket">Work jacket</a>'
                return raw, {'content_type': 'text/html', 'effective_url': url}
        pages, failures, funnel = acquire_website(Pages(), SUBJECT, {'navn': 'Example AS'}, Discovery(), 6)
        self.assertEqual(pages[0][1]['effective_url'], 'https://example.com/nb-no/terms')
        self.assertNotIn('https://example.com/fr-ch/terms', seen)
        self.assertIn('https://example.com/nb-no/products/jacket', seen)
        self.assertEqual(failures, [])

    def test_sampler_does_not_round_away_employers_in_many_industry_cells(self):
        rows = [{'organisation_number': f'{i:09}', 'employees': 0 if i < 850 else 20,
                 'industry_code': str(i), 'municipality_number': str(i), 'legal_form': 'AS'} for i in range(1000)]
        chosen, manifest = sample(rows, total=100)
        self.assertEqual(sum(r['stratum'][0] == '10_49' for r in chosen), 15)
        self.assertEqual(manifest['population'], 1000)
        self.assertEqual(chosen, sample(reversed(rows), total=100)[0])

    def test_full_nav_worker_then_refresh_and_independent_audit(self):
        config = load(ROOT / 'configs/local-external.json'); config.update(min_host_interval_seconds=0, max_retries=0,
                                                                        enabled_sources=['brreg_entity', 'nav_jobs'])
        frames, stopped = [], [False]
        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass
        def transport(fetcher, url, timeout, limit, headers=None):
            if url.endswith('/publicToken'): return 200, {'content-type': 'text/plain'}, b'current token aaa.bbb.ccc'
            if url.endswith('/feed'):
                body = {'items': [{'url': JOB_URL, '_feed_entry': {'status': 'ACTIVE', 'businessName': 'Example AS'}}], 'next_url': None}
            elif url == JOB_URL:
                body = {'uuid': UUID, 'status': 'INACTIVE' if stopped[0] else 'ACTIVE', 'ad_content': {
                    'uuid': UUID, 'title': 'Painter', 'published': '2026-10-01T00:00:00Z', 'expires': '2099-01-01T00:00:00Z',
                    'employer': {'orgnr': EMPLOYER, 'description': 'Example produces paints.'}}}
            elif '/underenheter/' in url: body = {'organisasjonsnummer': EMPLOYER, 'overordnetEnhet': SUBJECT}
            else: body = {'organisasjonsnummer': SUBJECT, 'navn': 'Example AS', '_links': {'self': {'href': url}}}
            raw = json.dumps(body).encode(); fetcher.budget.consume(len(raw))
            return 200, {'content-type': 'application/json'}, raw
        job = {'store': self.store.root, 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 5, 'started_at': WHEN, 'run_id': 'nav-test'}
        with patch('shirushi.fetch.Fetcher._request', transport):
            worker(Connection(), job)
            self.assertFalse([f for f in frames if f[0] == 'fatal'])
            first = next(f[2]['envelope'] for f in frames if f[0] == 'result')
            self.assertEqual(validate_envelopes([{'organisation_number': SUBJECT}], [first], load(ROOT / 'contracts/company-envelope.v1.json')), [])
            audit = SourceAudit(self.store.root, [SUBJECT]); evidence = {e['id']: e for e in first['evidence']}
            for c in first['claims']: audit.claim(SUBJECT, c, evidence)
            self.assertTrue(any(c['field'] == 'job_posting' and c['availability'] == 'available' for c in first['claims']))
            stopped[0] = True; frames.clear(); job.update(previous={SUBJECT: first}, deadline=time.monotonic() + 5)
            worker(Connection(), job)
            self.assertFalse([f for f in frames if f[0] in ('fatal', 'invalid_previous')])
            second = next(f[2]['envelope'] for f in frames if f[0] == 'result')
            self.assertFalse(any(c['field'] == 'job_posting' and c['availability'] == 'available' for c in second['claims']))
            self.assertNotIn('jobs_dated_activity', {o['family'] for o in second['opportunities'] if o['status'] == 'covered'})
            evidence = {e['id']: e for e in second['evidence']}
            for c in second['claims'] + second['history']: audit.claim(SUBJECT, c, evidence)
