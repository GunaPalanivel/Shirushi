"""Showcase summaries are derived from claims only: every sentence cites claims it can be rebuilt from."""
import copy
import json
import re
import tempfile
import unittest
from html import unescape
from pathlib import Path

from shirushi.showcase import AVAILABILITY_LABELS, availability_text, profile, render, summary_parts

SUBJECT = '912345678'
WHEN = '2026-10-10T08:00:00+00:00'
EARLIER = '2026-09-01T08:00:00+00:00'


def evidence(key, url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, span='span ' + 'x'):
    return {'id': 'snap:' + key, 'snapshot_id': 'snap', 'source_url': url, 'source_class': 'frozen_registry',
            'source_origin': url.split('/')[2], 'retrieved_at': EARLIER, 'content_sha256': 'ab' * 32,
            'claim_span': span, 'extraction_method': 'registry_csv_column_v1', 'locator': {'field': key}}


def claim(field, value, scope='frozen_registry', **extra):
    result = {'field': field, 'value': value, 'availability': 'available', 'evidence_ids': ['snap:' + field],
              'scope': scope, 'freshness': 'frozen_snapshot', 'first_observed_at': WHEN, 'last_observed_at': WHEN}
    result.update(extra)
    return result


def missing(field, availability, reason):
    return {'field': field, 'value': None, 'availability': availability, 'reason': reason, 'evidence_ids': []}


def envelope():
    claims = [
        claim('legal_name', 'EKSEMPEL AS'), claim('legal_form', 'AS'), claim('registered_employees', 12),
        claim('registered_municipality', 'BERGEN'), claim('industry_code', '62.010'),
        claim('industry_label', 'Programmeringstjenester'),
        claim('verified_website', 'https://eksempel.example/', scope='company_owned_html', freshness='live_source'),
        claim('business_description', 'Eksempel AS lager programvare for havner og skip.', scope='company_owned_html',
              freshness='live_source'),
        claim('social_profile', {'platform': 'linkedin', 'url': 'https://www.linkedin.com/company/eksempel/'},
              scope='company_owned_html', freshness='live_source'),
        claim('annual_revenue', {'amount': 5000000.0, 'currency': 'NOK', 'period': {'fraDato': '2025-01-01', 'tilDato': '2025-12-31'}},
              scope='entity_accounts', period={'fraDato': '2025-01-01', 'tilDato': '2025-12-31'}, freshness='live_source'),
        claim('registered_role:a', {'role_code': 'DAGL', 'role_label': 'Daglig leder', 'person_name': 'Kari Nordmann'}),
        claim('registered_role:b', {'role_code': 'LEDE', 'role_label': 'Styrets leder', 'person_name': 'Ola Nordmann'}),
        claim('operating_location', {'subunit_number': '1', 'name': 'EKSEMPEL AS', 'address': {'poststed': 'BERGEN'}}),
        claim('public_activity', {'statement': 'Eksempel AS lanserte en ny tjeneste.', 'published_at': '2026-09-30',
                                  'source_url': 'https://eksempel.example/nyheter/1'}, scope='company_owned_html'),
        missing('coverage:people', 'failed', 'Route not scheduled'),
        missing('coverage:jobs_dated_activity', 'not_available', 'No supported fact in checked source'),
        missing('coverage:financials_history', 'ambiguous', 'Conflicting source values for the same claim slot'),
        missing('coverage:operating_locations', 'blocked', 'robots.txt disallows the page'),
    ]
    ev = []
    for c in claims:
        if c['availability'] == 'available':
            url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT
            if c['scope'] == 'company_owned_html':
                url = 'https://eksempel.example/'
            if c['scope'] == 'entity_accounts':
                url = 'https://data.brreg.no/regnskapsregisteret/regnskap/' + SUBJECT
            ev.append(evidence(c['field'], url))
    return {'organisation_number': SUBJECT, 'claims': claims, 'evidence': ev, 'history': [], 'changes': [], 'errors': [],
            'run': {'run_id': 'r', 'started_at': WHEN, 'completed_at': WHEN, 'terminal_status': 'completed'},
            'opportunities': [{'family': f, 'status': 'covered', 'reason': 'supported_source_fact', 'scope': 'x'}
                              for f in ('business_products', 'website_owned_profiles')] +
                             [{'family': f, 'status': 'unknown', 'reason': 'no_verified_fact', 'scope': 'x'}
                              for f in ('people', 'jobs_dated_activity', 'financials_history', 'operating_locations')]}


def with_change(env):
    env = copy.deepcopy(env)
    env['changes'] = [{'field': 'registered_employees', 'kind': 'value_changed', 'old_value': 9, 'new_value': 12,
                       'old_evidence_ids': ['snap:registered_employees'], 'new_evidence_ids': ['snap:registered_employees'],
                       'observed_at': WHEN}]
    env['history'] = [claim('registered_employees', 9, first_observed_at=EARLIER, last_observed_at=EARLIER)]
    return env


def rebuild_without(env, indexes):
    smaller = copy.deepcopy(env)
    smaller['claims'] = [c for i, c in enumerate(smaller['claims']) if i not in indexes]
    return smaller


class SummaryTraceabilityTests(unittest.TestCase):
    def check_parts(self, env):
        parts = summary_parts(env)
        self.assertTrue(parts)
        for part in parts:
            cited = part['claims']
            self.assertTrue(cited or part['changes'], 'sentence without a citation: ' + part['text'])
            for index in cited:
                self.assertLess(index, len(env['claims']))
            for index in part['changes']:
                self.assertLess(index, len(env['changes']))
            self.assertTrue(part['text'].strip())
        return parts

    def test_every_sentence_cites_claims_and_repeats_only_their_values(self):
        env = with_change(envelope())
        for part in self.check_parts(env):
            allowed = ''
            for index in part['claims']:
                c = env['claims'][index]
                allowed += ' ' + json.dumps(c['value'], ensure_ascii=False) + ' ' + str(c.get('reason', '')) + ' ' + json.dumps(c.get('period') or '')
                if part['section'] in ('what', 'found') and c['availability'] != 'available':
                    self.fail('available-section sentence cites an unavailable claim: ' + part['text'])
                if part['section'] == 'unknown':
                    self.assertNotEqual(c['availability'], 'available', part['text'])
            for index in part['changes']:
                allowed += ' ' + json.dumps(env['changes'][index], ensure_ascii=False)
            allowed += ' ' + SUBJECT + ' ' + WHEN[:10] + ' ' + EARLIER[:10]
            tokens = re.findall(r'\d[\d.,]*', part['text'])
            for token in tokens:
                token = token.rstrip('.,')
                self.assertTrue(token in allowed or token == str(len(part['claims'])) or token == str(len(part['changes'])),
                                'number %r in %r not traceable to a cited claim' % (token, part['text']))

    def test_sentence_disappears_when_its_claims_are_removed(self):
        env = with_change(envelope())
        base = summary_parts(env)
        for part in base:
            if not part['claims']:
                continue
            smaller = rebuild_without(env, set(part['claims']))
            remaining = [p['text'] for p in summary_parts(smaller)]
            self.assertNotIn(part['text'], remaining, 'sentence survives removal of its claims: ' + part['text'])

    def test_what_it_is_names_form_industry_employees_and_municipality(self):
        text = ' '.join(p['text'] for p in summary_parts(envelope()) if p['section'] == 'what')
        for expected in ('EKSEMPEL AS', 'AS', 'BERGEN', 'Programmeringstjenester', '12'):
            self.assertIn(expected, text)

    def test_found_covers_website_description_profiles_and_dated_activity(self):
        text = ' '.join(p['text'] for p in summary_parts(envelope()) if p['section'] == 'found')
        for expected in ('https://eksempel.example/', 'havner og skip', 'linkedin', 'lanserte en ny tjeneste', '2026-09-30'):
            self.assertIn(expected, text)

    def test_no_claim_is_made_for_an_absent_website(self):
        env = envelope()
        env['claims'] = [c for c in env['claims'] if c['field'] not in ('verified_website', 'social_profile', 'business_description')]
        text = ' '.join(p['text'] for p in summary_parts(env))
        self.assertNotIn('eksempel.example', text)
        self.assertNotIn('linkedin', text)

    def test_unknowns_give_reason_and_state(self):
        parts = [p for p in summary_parts(envelope()) if p['section'] == 'unknown']
        text = ' '.join(p['text'] for p in parts)
        self.assertIn('Route not scheduled', text)
        self.assertIn('not checked', text.lower())
        self.assertIn('No supported fact in checked source', text)
        self.assertIn('Conflicting source values', text)
        self.assertIn('ambiguous', text.lower())
        self.assertIn('robots.txt disallows the page', text)
        self.assertIn('blocked', text.lower())
        for part in parts:
            self.assertTrue(part['claims'])

    def test_changes_are_stated_with_old_new_and_date_only_when_present(self):
        none = ' '.join(p['text'] for p in summary_parts(envelope()) if p['section'] == 'changed')
        self.assertIn('No changed values', none)
        self.assertNotRegex(none, r'\bchanged from\b')
        env = with_change(envelope())
        changed = [p for p in summary_parts(env) if p['section'] == 'changed']
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]['changes'], [0])
        for expected in ('Registered employees', '9', '12', '2026-10-10'):
            self.assertIn(expected, changed[0]['text'])

    def test_job_changes_are_not_republished(self):
        env = with_change(envelope())
        env['changes'].append({'field': 'job_posting', 'kind': 'current_support_lost', 'old_value': {'title': 'Secret vacancy'},
                               'new_value': None, 'old_evidence_ids': [], 'new_evidence_ids': [], 'observed_at': WHEN})
        self.assertNotIn('Secret vacancy', ' '.join(p['text'] for p in summary_parts(env)))

    def test_rendered_summary_marks_each_sentence_with_its_claims(self):
        html = profile(with_change(envelope()))
        sentences = re.findall(r'<li class="sentence" data-section="(\w+)" data-claims="([^"]*)"', html)
        self.assertGreaterEqual(len(sentences), 6)
        for section, claims in sentences:
            self.assertIn(section, ('what', 'found', 'changed', 'unknown'))
        self.assertTrue(all(claims for _section, claims in sentences))

    def test_summary_text_is_escaped(self):
        env = envelope()
        env['claims'][0]['value'] = '<img src=x onerror=alert(1)> AS'
        html = profile(env)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x', html)

    def test_retained_run_summaries_are_traceable(self):
        path = Path(__file__).resolve().parents[1] / 'out/attribution-representative-native-20261011/output.jsonl'
        if not path.exists():
            self.skipTest('retained run output not present')
        for line in path.read_text(encoding='utf-8').splitlines()[:30]:
            env = json.loads(line)
            for part in summary_parts(env):
                self.assertTrue(part['claims'] or part['changes'])
                for index in part['claims']:
                    self.assertLess(index, len(env['claims']))


class AvailabilityStateTests(unittest.TestCase):
    def test_every_contract_state_has_a_readable_label(self):
        for state in ('available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'):
            label = availability_text(state)
            self.assertIn(state, AVAILABILITY_LABELS)
            self.assertNotIn('_', label)
            self.assertTrue(label[0].isupper())
        self.assertEqual(len({availability_text(s) for s in AVAILABILITY_LABELS}), len(AVAILABILITY_LABELS))

    def test_profile_shows_state_label_and_reason_for_non_available_rows(self):
        html = unescape(profile(envelope()))
        for expected in ('Not checked', 'Not found in checked sources', 'Ambiguous', 'Blocked',
                         'Route not scheduled', 'robots.txt disallows the page'):
            self.assertIn(expected, html)


class EvidenceVisibilityTests(unittest.TestCase):
    def test_each_available_fact_shows_source_host_retrieval_date_and_hash(self):
        html = unescape(profile(envelope()))
        rows = re.findall(r'<tr id="fact-\d+".*?</tr>', html, re.S)
        self.assertEqual(len(rows), len(envelope()['claims']))
        available = [r for r in rows if 'class="state-available"' in r]
        self.assertGreaterEqual(len(available), 14)
        for row in available:
            self.assertRegex(row, r'class="source-line"')
            self.assertIn('2026-09-01', row)
            self.assertRegex(row, r'(data\.brreg\.no|eksempel\.example)')
            self.assertTrue('SHA-256' in row or 'href="#evidence-' in row)
        self.assertEqual(html.count('SHA-256: ' + 'ab' * 32), len({e['id'] for e in envelope()['evidence']}))

    def test_source_links_are_https_and_noopener(self):
        html = profile(envelope())
        for tag in re.findall(r'<a [^>]*href="https?://[^"]*"[^>]*>', html):
            self.assertIn('href="https://', tag)
            self.assertIn('rel="noopener noreferrer"', tag)

    def test_http_source_is_refused(self):
        env = envelope()
        env['evidence'][0]['source_url'] = 'http://example.com/'
        with self.assertRaises(ValueError):
            profile(env)


class SiteTests(unittest.TestCase):
    def build(self, count=3):
        envelopes = []
        for number in range(count):
            env = copy.deepcopy(envelope())
            env['organisation_number'] = str(912345000 + number)
            env['claims'][0]['value'] = 'FIRMA %d AS' % number
            if number % 2:
                env['claims'] = [c for c in env['claims'] if c['field'] not in ('verified_website', 'social_profile')]
            envelopes.append(env)
        envelopes.append(with_change(envelopes[0]) | {'organisation_number': '912349999'})
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return envelopes, Path(folder.name)

    def test_two_renders_are_byte_identical(self):
        envelopes, base = self.build()
        render(envelopes, base / 'a')
        render(copy.deepcopy(envelopes), base / 'b')
        files = sorted(p.relative_to(base / 'a') for p in (base / 'a').rglob('*') if p.is_file())
        self.assertEqual(files, sorted(p.relative_to(base / 'b') for p in (base / 'b').rglob('*') if p.is_file()))
        for name in files:
            self.assertEqual((base / 'a' / name).read_bytes(), (base / 'b' / name).read_bytes(), str(name))

    def test_pages_are_self_contained(self):
        envelopes, base = self.build()
        render(envelopes, base / 'a')
        for page in (base / 'a/signalpost').glob('*.html'):
            html = page.read_text(encoding='utf-8')
            self.assertNotRegex(html, r'<link\b|\bsrc\s*=|@import|url\(|<iframe|<img|\bfetch\(|XMLHttpRequest')
            self.assertNotRegex(html, r'(?:src|action)="https?://')

    def test_index_has_search_filters_sort_and_compare_controls(self):
        envelopes, base = self.build()
        render(envelopes, base / 'a')
        html = (base / 'a/signalpost/index.html').read_text(encoding='utf-8')
        self.assertIn('<label for="search">', html)
        for key in ('website', 'description', 'profiles', 'activity', 'financials', 'changed'):
            self.assertIn('data-filter="%s"' % key, html)
        self.assertIn('id="sort"', html)
        self.assertIn('id="compare-panel"', html)
        self.assertEqual(len(re.findall(r'<li class="company"', html)), 4)
        self.assertRegex(html, r'class="company"[^>]*data-areas="\d"')
        self.assertIn('data-company=', html)
        self.assertIn('>Compare selected companies</button>', html)
        self.assertIn('id="comparison"', html)

    def test_index_search_text_covers_name_number_municipality_and_industry(self):
        envelopes, base = self.build(1)
        render(envelopes, base / 'a')
        html = (base / 'a/signalpost/index.html').read_text(encoding='utf-8')
        card = re.search(r'<li class="company"[^>]*data-search="([^"]*)"', html).group(1)
        for expected in ('firma 0 as', '912345000', 'bergen', 'programmeringstjenester'):
            self.assertIn(expected, card)

    def test_site_size_stays_reasonable_for_100_companies(self):
        envelopes, base = self.build(100)
        render(envelopes, base / 'a')
        total = sum(p.stat().st_size for p in (base / 'a').rglob('*') if p.is_file())
        self.assertLess(total, 2_500_000)


if __name__ == '__main__':
    unittest.main()
