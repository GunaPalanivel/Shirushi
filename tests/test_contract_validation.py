"""Boundary counterexamples independent of any future maker or crawler."""
import copy
import tempfile
import unittest
from pathlib import Path

from tools.validate_contracts import ROOT, load, timestamp, validate_config, validate_envelopes, validate_inputs


class ContractValidationTests(unittest.TestCase):
    def setUp(self):
        self.policy = load(ROOT / 'configs/source-policy.json')
        self.config = load(ROOT / 'configs/local-pilot.json')
        self.contract = load(ROOT / 'contracts/company-envelope.v1.json')
        self.inputs = [{'organisation_number': '810034882'}]
        # Synthetic fixture: shape is valid; no real source-support claim made.
        self.envelope = {
            'organisation_number': '810034882',
            'run': {'run_id': 'shape-fixture', 'started_at': '2026-10-07T10:00:00Z',
                    'completed_at': '2026-10-07T10:00:01Z', 'terminal_status': 'completed'},
            'claims': [{'field': 'employees', 'value': 0, 'availability': 'available', 'evidence_ids': ['e1']}],
            'evidence': [{'id': 'e1', 'source_url': 'https://fixture.example/row', 'source_class': 'synthetic',
                          'retrieved_at': '2026-10-07T09:00:00Z', 'content_sha256': 'a' * 64,
                          'claim_span': 'employees: 0', 'extraction_method': 'fixture', 'locator': {'field': 'employees'}}],
            'changes': [], 'errors': [], 'operations': {'requests': 0, 'runtime_ms': 1, 'third_party_cost_usd': 0}}

    def check_envelope(self, envelope=None, inputs=None):
        return validate_envelopes(inputs or self.inputs, [envelope or self.envelope], self.contract)

    def test_local_profiles_pass(self):
        for path in (ROOT / 'configs').glob('local-*.json'):
            self.assertEqual(validate_config(load(path), self.policy), [], path.name)

    def test_official_template_refused(self):
        errors = validate_config(load(ROOT / 'configs/official-run.template.json'), self.policy)
        self.assertIn('Official wire schema not confirmed', errors)
        self.assertIn('Official setting unconfirmed: organizer_settings_receipt', errors)

    def test_disabled_and_conditional_sources_refused(self):
        for source in ('norid_batch', 'search_api', 'brreg_api', 'unknown'):
            config = copy.deepcopy(self.config)
            config['enabled_sources'].append(source)
            self.assertTrue(validate_config(config, self.policy))

    def test_nonfinite_boolean_negative_budget_refused(self):
        for value in (float('nan'), float('inf'), True, -1):
            config = copy.deepcopy(self.config)
            config['third_party_cost_usd'] = value
            self.assertTrue(validate_config(config, self.policy))

    def test_unknown_config_key_refused(self):
        self.config['request_buget'] = 999
        self.assertTrue(validate_config(self.config, self.policy))

    def test_malformed_mode_is_rejected_without_crash(self):
        for value in ([], {}, None, 'unknown'):
            config = copy.deepcopy(self.config)
            config['mode'] = value
            self.assertIn('Mode must be local or official', validate_config(config, self.policy))

    def test_no_finalization_time_refused(self):
        self.config['finalization_reserve_fraction'] = 0
        self.assertTrue(validate_config(self.config, self.policy))

    def test_json_duplicate_keys_and_nan_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for body in ('{"workers": 8, "workers": 80}', '{"cost": NaN}', '{"cost": 1e999}'):
                path.write_text(body, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load(path)

    def test_invalid_and_duplicate_inputs_refused(self):
        for identity in (810034882, '810 034 882', '81003488', '８１００３４８８２'):
            self.assertTrue(validate_inputs([{'organisation_number': identity}])[0])
        self.assertTrue(validate_inputs(self.inputs * 2)[0])

    def test_wrong_id_same_count_refused(self):
        self.envelope['organisation_number'] = '999999999'
        self.assertIn('Output identities must exactly match input order and membership', self.check_envelope())

    def test_reordered_or_dropped_batch_refused(self):
        second = copy.deepcopy(self.envelope)
        second['organisation_number'] = '999999999'
        inputs = self.inputs + [{'organisation_number': '999999999'}]
        for output in ([second, self.envelope], [self.envelope]):
            self.assertTrue(validate_envelopes(inputs, output, self.contract))

    def test_available_zero_not_confused_with_missing(self):
        self.assertEqual(self.check_envelope(), [])
        self.envelope['claims'][0].update(value=None)
        self.assertTrue(self.check_envelope())

    def test_six_availability_states_and_explicit_reason(self):
        for state in self.contract['availability_states']:
            envelope = copy.deepcopy(self.envelope)
            if state != 'available':
                envelope['claims'][0].update(availability=state, value=None, reason='Fixture checked route', evidence_ids=[])
            self.assertEqual(self.check_envelope(envelope), [], state)
        self.envelope['claims'][0].update(availability='not_available', value=0, reason='No result')
        self.assertTrue(self.check_envelope())

    def test_starter_state_leak_refused(self):
        self.envelope['claims'][0]['availability'] = 'not_found'
        self.assertTrue(self.check_envelope())

    def test_dangling_and_duplicate_evidence_refused(self):
        self.envelope['claims'][0]['evidence_ids'] = ['missing']
        self.assertTrue(self.check_envelope())
        self.envelope['claims'][0]['evidence_ids'] = ['e1']
        self.envelope['evidence'].append(copy.deepcopy(self.envelope['evidence'][0]))
        self.assertTrue(self.check_envelope())

    def test_missing_hash_method_or_locator_refused(self):
        for key in ('content_sha256', 'extraction_method', 'locator'):
            envelope = copy.deepcopy(self.envelope)
            del envelope['evidence'][0][key]
            self.assertTrue(self.check_envelope(envelope), key)

    def test_timestamp_without_timezone_or_backwards_refused(self):
        self.envelope['run']['started_at'] = '2026-10-07T10:00:00'
        self.assertTrue(self.check_envelope())
        self.envelope['run']['started_at'] = '2026-10-07T11:00:00Z'
        self.assertTrue(self.check_envelope())

    def test_rfc3339_profile_accepts_known_offsets(self):
        utc = timestamp('2026-10-07T10:00:00Z')
        self.assertEqual(utc, timestamp('2026-10-07T15:30:00+05:30'))
        self.assertEqual(timestamp('2026-10-07T10:00:00.123456Z').microsecond, 123456)

    def test_rfc3339_profile_refuses_ambiguous_or_nonstandard_shapes(self):
        for value in ('2026-10-07 10:00:00+00:00', '20261007T100000Z',
                      '2026-10-07T10:00:00-00:00', '2026-10-07T10:00:00+0000',
                      '2026-10-07T10:00:00+00:99', '2026-10-07T10:00:00+24:00',
                      '2026-02-30T10:00:00Z', '2026-10-07T10:00:60Z',
                      '2026-10-07T10:00:00.1234567Z'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value)

    def test_no_publication_still_terminates(self):
        self.envelope.update(claims=[], evidence=[])
        self.envelope['run']['terminal_status'] = 'failed'
        self.envelope['errors'] = [{'code': 'source_failed'}]
        self.assertEqual(self.check_envelope(), [])

    def test_shape_cannot_establish_source_truth(self):
        self.envelope['claims'][0]['value'] = 999999
        self.assertEqual(self.check_envelope(), [])
        # Deliberate limit: the evidence checker must inspect bytes and subject.


if __name__ == '__main__':
    unittest.main()
