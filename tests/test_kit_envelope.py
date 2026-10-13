"""Kit-compatible envelope blocks: derivable from claims, deterministic, never a new fact."""
import copy
import json
import unittest

from shirushi.contracts import ROOT, load
from shirushi.kitcompat import KIT_KEYS, confidence
from shirushi.wire import convert
from shirushi_eval.wire import internal_records, validate_kit_blocks, validate_public_contract

SUBJECT = '923609016'
OTHER = '810034882'
WHEN = '2026-10-08T08:00:00+00:00'
DONE = '2026-10-08T08:00:09+00:00'
REGISTRY_URL = 'https://example.org/frozen'
PAGE_URL = 'https://example.no/'
LINKEDIN = {'platform': 'linkedin', 'url': 'https://linkedin.com/company/example',
            'handle_key': 'linkedin.com/company/example'}
FACEBOOK = {'platform': 'facebook', 'url': 'https://facebook.com/Example', 'handle_key': 'facebook.com/example'}


def evidence(eid, source_class, url, digit='a', retrieved=WHEN):
    return {'id': eid, 'snapshot_id': 'snap-' + eid, 'source_url': url, 'source_class': source_class,
            'retrieved_at': retrieved, 'content_sha256': digit * 64, 'claim_span': 'span ' + eid,
            'locator': {'field': eid}, 'extraction_method': 'fixture_v1'}


def claim(field, value, eid, scope, family=None):
    result = {'field': field, 'value': value, 'availability': 'available', 'evidence_ids': [eid], 'scope': scope,
              'freshness': 'live_source'}
    if family:
        result['family'] = family
    return result


def missing(field, availability, reason):
    return {'field': field, 'value': None, 'availability': availability, 'reason': reason, 'evidence_ids': []}


def internal(claims, evidences, terminal='completed', subject=SUBJECT):
    return {'organisation_number': subject,
            'run': {'run_id': 'fixture-0000', 'started_at': WHEN, 'completed_at': DONE, 'terminal_status': terminal},
            'claims': claims, 'evidence': evidences, 'changes': [], 'errors': [], 'history': [],
            'operations': {'requests': 0, 'runtime_ms': 1, 'third_party_cost_usd': 0}}


def registry_claims(employees=0):
    claims = [claim('legal_name', 'EXAMPLE PUMPS AS', 'e-name', 'frozen_registry'),
              claim('legal_form', 'AS', 'e-form', 'frozen_registry'),
              claim('registered_municipality', 'OSLO', 'e-town', 'frozen_registry')]
    if employees is not None:
        claims.append(claim('registered_employees', employees, 'e-staff', 'frozen_registry'))
    return claims, [evidence(e, 'frozen_registry', REGISTRY_URL, 'b') for e in ('e-name', 'e-form', 'e-town', 'e-staff')
                    if employees is not None or e != 'e-staff']


def covered(socials=(LINKEDIN,), employees=0):
    claims, evidences = registry_claims(employees)
    claims.append(claim('verified_website', PAGE_URL, 'e-web', 'company_owned_html', 'website_owned_profiles'))
    claims.extend(claim('social_profile', dict(s), 'e-web', 'verified_site_link', 'website_owned_profiles')
                  for s in socials)
    return internal(claims, evidences + [evidence('e-web', 'company_owned', PAGE_URL, 'c')])


def blocked_website(reason='Fetch refused by robots.txt', availability='blocked'):
    claims, evidences = registry_claims()
    claims.append(missing('coverage:website_owned_profiles', availability, reason))
    return internal(claims, evidences)


def website_record(wire):
    return wire['profile']['evidence']['website']


class KitBlocksTests(unittest.TestCase):
    def kit(self, envelope):
        return convert([envelope])[0]

    def test_covered_company_carries_the_registry_subset_and_the_verified_website(self):
        wire = self.kit(covered(socials=(FACEBOOK, LINKEDIN)))
        self.assertEqual(wire['run_id'], 'fixture-0000')
        self.assertEqual((wire['started_at'], wire['completed_at'], wire['state']), (WHEN, DONE, 'complete'))
        profile = wire['profile']
        self.assertEqual((profile['organisation_number'], profile['name'], profile['legal_form'],
                          profile['employees'], profile['municipality']), (SUBJECT, 'EXAMPLE PUMPS AS', 'AS', 0, 'OSLO'))
        self.assertEqual(profile['evidence']['registry_live']['value'],
                         {'organisation_number': SUBJECT, 'name': 'EXAMPLE PUMPS AS', 'legal_form': 'AS', 'employees': 0})
        site = website_record(wire)
        self.assertEqual((site['status'], site['availability'], site['source_url']), ('available', 'available', PAGE_URL))
        self.assertEqual(site['evidence_ids'], ['e-web'])
        self.assertEqual(site['value']['final_url'], PAGE_URL)
        self.assertTrue(site['value']['identity_assessment']['publishable'])
        # Sorted by platform then URL regardless of claim order.
        self.assertEqual(site['value']['social_links'], [{'platform': 'facebook', 'url': FACEBOOK['url']},
                                                         {'platform': 'linkedin', 'url': LINKEDIN['url']}])
        self.assertEqual({m: s['state'] for m, s in wire['modules'].items()}, {'registry': 'complete',
                         'registry_live': 'complete', 'website': 'complete'})
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])

    def test_public_claims_are_unchanged_except_for_confidence(self):
        source = covered()
        wire = self.kit(source)
        stripped = [{k: v for k, v in c.items() if k != 'confidence'} for c in wire['claims']]
        expected = copy.deepcopy(source['claims'])
        next(c for c in expected if c['field'] == 'verified_website')['field'] = 'official_website'
        self.assertEqual(stripped, expected)
        self.assertEqual(wire['evidence'], source['evidence'])
        self.assertTrue(all(0 < c['confidence'] <= 1 for c in wire['claims']))
        self.assertEqual(internal_records([wire])[0], source)

    def test_zero_employees_is_kept_and_a_missing_count_is_absent(self):
        zero = self.kit(covered(employees=0))['profile']
        self.assertIs(type(zero['employees']), int)
        self.assertEqual(zero['employees'], 0)
        self.assertEqual(zero['evidence']['registry_live']['value']['employees'], 0)
        claims, evidences = registry_claims(employees=None)
        claims.append(missing('registered_employees', 'not_available', 'absent_in_frozen_row'))
        absent = self.kit(internal(claims, evidences))['profile']
        self.assertNotIn('employees', absent)
        self.assertNotIn('employees', absent['evidence']['registry_live']['value'])

    def test_not_found_company_keeps_the_registry_anchor_and_reports_the_website_as_not_found(self):
        claims, evidences = registry_claims()
        claims.append(missing('verified_website', 'not_available', 'No legally attributable website candidate'))
        wire = self.kit(internal(claims, evidences))
        site = website_record(wire)
        self.assertEqual((site['status'], site['availability'], site['value']), ('not_found', 'not_available', None))
        self.assertEqual(site['reason'], 'No legally attributable website candidate')
        self.assertEqual(wire['modules']['website']['state'], 'not_found')
        self.assertEqual(wire['profile']['name'], 'EXAMPLE PUMPS AS')
        self.assertEqual([c['confidence'] for c in wire['claims'] if c['availability'] != 'available'], [0.0])
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])

    def test_every_availability_state_maps_to_a_kit_status_and_module_state(self):
        expected = {'not_available': ('not_found', 'not_found'), 'ambiguous': ('not_found', 'not_found'),
                    'blocked': ('blocked', 'blocked_policy'), 'failed': ('source_error', 'source_error'),
                    'not_applicable': ('not_applicable', 'not_applicable')}
        for availability, (status, state) in expected.items():
            with self.subTest(availability):
                wire = self.kit(blocked_website('Not checked: ' + availability, availability))
                site = website_record(wire)
                self.assertEqual((site['status'], site['availability'], site['value']), (status, availability, None))
                self.assertEqual(wire['modules']['website']['state'], state)
                self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])
        available = self.kit(covered())
        self.assertEqual((website_record(available)['status'], available['modules']['website']['state']),
                         ('available', 'complete'))

    def test_robots_and_budget_reasons_select_the_specific_module_state(self):
        self.assertEqual(self.kit(blocked_website('Fetch refused by robots.txt'))['modules']['website']['state'],
                         'blocked_robots')
        exhausted = self.kit(blocked_website('Request budget exhausted', 'failed'))
        self.assertEqual(exhausted['modules']['website']['state'], 'budget_exhausted')
        self.assertEqual(website_record(exhausted)['status'], 'source_error')

    def test_failed_company_is_a_submission_error_with_modules_from_its_claims(self):
        failed = blocked_website('source_failure: Worker exited', 'failed')
        failed['run']['terminal_status'] = 'failed'
        failed['errors'] = [{'stage': 'supervisor', 'reason': 'Worker exited'}]
        wire = self.kit(failed)
        self.assertEqual(wire['state'], 'submission_error')
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])

    def test_modules_follow_attempted_families_and_never_invent_unattempted_ones(self):
        claims, evidences = registry_claims()
        wire = self.kit(internal(claims, evidences))
        self.assertEqual(sorted(wire['modules']), ['registry', 'registry_live'])
        self.assertNotIn('website', wire['profile']['evidence'])
        claims.append(missing('coverage:financials_history', 'not_available', 'No accounts filed'))
        claims.append(claim('registered_role:daglig_leder', {'name': 'A'}, 'e-role', 'registered_role_snapshot', 'people'))
        claims.append(claim('operating_location', {'subunit_number': OTHER}, 'e-loc', 'registered_subunit',
                            'operating_locations'))
        evidences += [evidence('e-role', 'brreg_roles_snapshot', 'https://data.brreg.no/r'),
                      evidence('e-loc', 'brreg_subunits', 'https://data.brreg.no/u', 'd', '2026-10-08T09:00:00+00:00')]
        wire = self.kit(internal(claims, evidences))
        self.assertEqual({m: s['state'] for m, s in wire['modules'].items()},
                         {'financials': 'not_found', 'locations': 'complete', 'registry': 'complete',
                          'registry_live': 'complete', 'roles': 'complete'})
        self.assertEqual(wire['modules']['locations']['final_timestamp'], '2026-10-08T09:00:00+00:00')
        self.assertEqual(wire['modules']['financials']['final_timestamp'], DONE)
        self.assertEqual(wire['modules']['roles']['retry_count'], 0)
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])

    def test_unverified_website_never_reaches_the_kit_website_record(self):
        claims, evidences = registry_claims()
        claims.append(claim('declared_website', 'https://declared.example/', 'e-decl', 'official_entity',
                            'website_owned_profiles'))
        claims.append(missing('verified_website', 'ambiguous', 'No exact legal operator proof'))
        evidences.append(evidence('e-decl', 'brreg_entity', 'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT))
        wire = self.kit(internal(claims, evidences))
        record = website_record(wire)
        self.assertEqual((record['status'], record['availability'], record['value']), ('not_found', 'ambiguous', None))
        self.assertNotIn('declared.example', json.dumps(record))
        self.assertEqual(wire['profile']['website'], 'https://declared.example/')  # a registry fact with its own claim
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])

    def test_social_links_need_a_verified_website_and_never_come_from_candidates(self):
        claims, evidences = registry_claims()
        claims.append(missing('verified_website', 'not_available', 'nothing found'))
        claims.append(missing('social_profile', 'not_applicable', 'No published official website'))
        wire = self.kit(internal(claims, evidences))
        self.assertNotIn('social_links', json.dumps(wire['profile']))

    def test_a_string_social_profile_becomes_social_links_beside_an_official_website(self):
        claims, evidences = registry_claims()
        claims.append(claim('verified_website', PAGE_URL, 'e-web', 'company_owned_html', 'website_owned_profiles'))
        claims.append(claim('social_profile', 'facebook.com/examplepumps', 'e-soc', 'registry_linked_html',
                            'website_owned_profiles'))
        evidences.extend((evidence('e-web', 'company_owned', PAGE_URL, 'c'),
                          evidence('e-soc', 'company_owned', PAGE_URL, 'd')))
        wire = self.kit(internal(claims, evidences))
        link = {'platform': 'facebook', 'url': 'https://facebook.com/examplepumps'}
        site = website_record(wire)['value']
        self.assertEqual(site['social_links'], [link])
        self.assertEqual(site['discovered_social_links'], [link])
        self.assertEqual(next(c['value'] for c in wire['claims'] if c['field'] == 'social_profile'),
                         'facebook.com/examplepumps')
        self.assertEqual(validate_public_contract([SUBJECT], [wire]), [])
        claims[-1] = claim('social_profile', 'not-a-profile', 'e-soc', 'registry_linked_html', 'website_owned_profiles')
        empty = website_record(self.kit(internal(claims, evidences)))['value']
        self.assertEqual(empty['social_links'], [])

    def test_output_is_deterministic_and_independent_of_claim_order(self):
        source = covered(socials=(FACEBOOK, LINKEDIN))
        first = json.dumps(convert([source]), sort_keys=True, ensure_ascii=False)
        self.assertEqual(first, json.dumps(convert([copy.deepcopy(source)]), sort_keys=True, ensure_ascii=False))
        shuffled = copy.deepcopy(source)
        shuffled['claims'].reverse()
        a, b = convert([source])[0], convert([shuffled])[0]
        self.assertEqual({k: a[k] for k in KIT_KEYS}, {k: b[k] for k in KIT_KEYS})
        # Re-serialising an already published record is a fixed point, not a second layer.
        self.assertEqual(convert(convert([source])), convert([source]))
        self.assertEqual(convert(convert([source], external=False), external=True), convert([source]))

    def test_kit_blocks_contain_no_value_outside_claims_evidence_and_the_run(self):
        source = covered(socials=(FACEBOOK, LINKEDIN))
        wire = self.kit(source)
        allowed = {SUBJECT, 'fixture-0000', WHEN, DONE, 'shirushi-kit-profile-v1'}
        for item in source['claims'] + source['evidence']:
            for value in item.values():
                if isinstance(value, dict):
                    allowed.update(v for v in value.values() if isinstance(v, str))
                elif isinstance(value, (str, int)):
                    allowed.add(value)
                elif isinstance(value, list):
                    allowed.update(v for v in value if isinstance(v, str))
        scalars = []

        def walk(node, path=()):
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, path + (key,))
            elif isinstance(node, list):
                for value in node:
                    walk(value, path)
            elif isinstance(node, str) and path[-1] not in ('field', 'status', 'source_type', 'availability', 'method',
                                                             'state', 'reason', 'note', 'adapter', 'method'):
                scalars.append(node)
        walk({key: wire[key] for key in KIT_KEYS if key != 'modules'})
        self.assertEqual([s for s in scalars if s not in allowed], [])

    def test_confidence_is_a_fixed_table_not_a_measurement(self):
        by_field = {c['field']: c['confidence'] for c in self.kit(covered())['claims']}
        self.assertEqual((by_field['legal_name'], by_field['official_website'], by_field['social_profile']), (1.0, 0.99, 0.9))
        gate = claim('verified_website', PAGE_URL, 'e', 'registry_declared_host_name_gate', 'website_owned_profiles')
        self.assertEqual(confidence(dict(gate, field='official_website')), 0.9)
        news = claim('dated_news', {'published_at': '2025-09-22T20:00:00+02:00'}, 'e', 'company_owned_article')
        self.assertEqual(confidence(news), 0.9)
        news['value']['published_at'] = '2025-09-22'
        self.assertEqual(confidence(news), 0.8)
        self.assertEqual(confidence(missing('social_profile', 'ambiguous', 'why')), 0.0)

    def test_contract_document_lists_the_published_blocks(self):
        adapter = load(ROOT / 'contracts/company-envelope.v1.json')['published_contract_adapter']
        self.assertEqual(adapter['kit_compatible_blocks'], list(KIT_KEYS))
        self.assertEqual(adapter['kit_profile_evidence'], ['registry_live', 'website'])
        self.assertTrue(adapter['kit_blocks_derived_from_claims'])


class KitValidatorTests(unittest.TestCase):
    """The independent validator must refuse kit values that no accepted claim supports."""
    def setUp(self):
        self.good = convert([covered()])[0]

    def errors(self, envelope):
        return validate_kit_blocks(envelope)

    def tampered(self, edit):
        envelope = copy.deepcopy(self.good)
        edit(envelope)
        return envelope

    def test_a_derived_envelope_passes_and_an_older_plain_envelope_is_still_accepted(self):
        self.assertEqual(self.errors(self.good), [])
        self.assertEqual(validate_public_contract([SUBJECT], [self.good]), [])
        plain = internal_records([self.good])[0]
        next(c for c in plain['claims'] if c['field'] == 'verified_website')['field'] = 'official_website'
        self.assertEqual(validate_public_contract([SUBJECT], [plain]), [])

    def test_social_link_without_a_matching_claim_is_rejected(self):
        def edit(e):
            e['profile']['evidence']['website']['value']['social_links'].append(
                {'platform': 'instagram', 'url': 'https://instagram.com/other'})
        self.assertTrue(self.errors(self.tampered(edit)))
        def drop_claim(e):
            e['claims'] = [c for c in e['claims'] if c['field'] != 'social_profile']
        self.assertTrue(self.errors(self.tampered(drop_claim)))

    def test_a_social_link_claim_in_a_non_available_state_does_not_support_the_link(self):
        def edit(e):
            for c in e['claims']:
                if c['field'] == 'social_profile':
                    c.update(value=None, availability='ambiguous', reason='handle name evidence absent',
                             evidence_ids=[], confidence=0.0)
        self.assertTrue(self.errors(self.tampered(edit)))

    def test_social_links_must_be_sorted_and_unique(self):
        both = convert([covered(socials=(FACEBOOK, LINKEDIN))])[0]
        links = both['profile']['evidence']['website']['value']['social_links']
        for broken in (list(reversed(links)), links + links[:1]):
            envelope = copy.deepcopy(both)
            envelope['profile']['evidence']['website']['value']['social_links'] = broken
            self.assertTrue(self.errors(envelope))

    def test_profile_values_must_equal_available_claims(self):
        for key, bad in (('name', 'OTHER AS'), ('legal_form', 'ASA'), ('employees', 1), ('municipality', 'BERGEN'),
                         ('employees', False), ('organisation_number', OTHER), ('website', 'https://x.example/')):
            with self.subTest(key):
                self.assertTrue(self.errors(self.tampered(lambda e: e['profile'].__setitem__(key, bad))))

    def test_profile_key_without_an_available_claim_is_rejected_and_so_is_a_missing_supported_key(self):
        claims, evidences = registry_claims(employees=None)
        claims.append(missing('registered_employees', 'not_available', 'absent_in_frozen_row'))
        envelope = convert([internal(claims, evidences)])[0]
        self.assertEqual(self.errors(envelope), [])
        envelope['profile']['employees'] = 0
        self.assertTrue(self.errors(envelope))
        del self.good['profile']['name']
        self.assertTrue(self.errors(self.good))

    def test_website_available_needs_an_available_official_website_claim_with_the_same_url(self):
        def other_url(e):
            e['profile']['evidence']['website']['value']['final_url'] = 'https://other.example/'
        self.assertTrue(self.errors(self.tampered(other_url)))
        def lose_claim(e):
            for c in e['claims']:
                if c['field'] == 'official_website':
                    c.update(value=None, availability='ambiguous', reason='no proof', evidence_ids=[], confidence=0.0)
        self.assertTrue(self.errors(self.tampered(lose_claim)))
        def unverified(e):
            e['profile']['evidence']['website']['value']['identity_assessment']['publishable'] = False
        self.assertTrue(self.errors(self.tampered(unverified)))

    def test_website_record_cannot_cite_foreign_evidence_or_a_different_hash(self):
        def hash_edit(e):
            e['profile']['evidence']['website']['content_sha256'] = 'f' * 64
        def url_edit(e):
            e['profile']['evidence']['website']['source_url'] = 'https://elsewhere.example/'
        def ids_edit(e):
            e['profile']['evidence']['website']['evidence_ids'] = ['e-nope']
        for edit in (hash_edit, url_edit, ids_edit):
            self.assertTrue(self.errors(self.tampered(edit)))

    def test_unavailable_website_record_cannot_carry_a_value_or_an_available_status(self):
        wire = convert([blocked_website('nothing', 'not_available')])[0]
        self.assertEqual(self.errors(wire), [])
        for edit in (lambda e: e['profile']['evidence']['website'].__setitem__('value', {'final_url': PAGE_URL}),
                     lambda e: e['profile']['evidence']['website'].__setitem__('status', 'available')):
            envelope = copy.deepcopy(wire)
            edit(envelope)
            self.assertTrue(self.errors(envelope))

    def test_modules_must_be_known_terminal_and_backed_by_claims(self):
        def unknown(e):
            e['modules']['group'] = dict(e['modules']['registry'])
        def not_terminal(e):
            e['modules']['website']['state'] = 'running'
        def unbacked(e):
            e['modules']['roles'] = dict(e['modules']['registry'])
        def lying(e):
            e['modules']['website']['state'] = 'not_found'
        def retried(e):
            e['modules']['website']['retry_count'] = 2
        def stamp(e):
            e['modules']['website']['final_timestamp'] = '2030-01-01T00:00:00+00:00'
        for edit in (unknown, not_terminal, unbacked, lying, retried, stamp):
            self.assertTrue(self.errors(self.tampered(edit)), edit.__name__)

    def test_run_copies_state_and_partial_blocks_are_checked(self):
        for edit in (lambda e: e.__setitem__('run_id', 'other'), lambda e: e.__setitem__('started_at', DONE),
                     lambda e: e.__setitem__('state', 'submission_error'), lambda e: e.pop('profile'),
                     lambda e: e.pop('modules')):
            self.assertTrue(self.errors(self.tampered(edit)))

    def test_confidence_must_be_a_probability_and_zero_only_without_a_value(self):
        for index, bad in ((0, 1.5), (0, True), (0, '1'), (0, 0.0)):
            envelope = copy.deepcopy(self.good)
            envelope['claims'][index]['confidence'] = bad
            self.assertTrue(self.errors(envelope), bad)
        envelope = copy.deepcopy(self.good)
        del envelope['claims'][0]['confidence']
        self.assertTrue(self.errors(envelope))

    def test_kit_registry_record_needs_the_legal_name_evidence(self):
        def edit(e):
            e['profile']['evidence']['registry_live']['evidence_ids'] = ['e-web']
        self.assertTrue(self.errors(self.tampered(edit)))
        def extra(e):
            e['profile']['evidence']['registry_live']['value']['bankrupt'] = False
        self.assertTrue(self.errors(self.tampered(extra)))

    def test_unknown_profile_evidence_module_is_rejected(self):
        def edit(e):
            e['profile']['evidence']['roles'] = e['profile']['evidence']['registry_live']
        self.assertTrue(self.errors(self.tampered(edit)))


if __name__ == '__main__':
    unittest.main()
