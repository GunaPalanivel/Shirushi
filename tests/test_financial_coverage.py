"""Financial interpretation, missing-company recovery and independent checking."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from shirushi.api_sources import ACCOUNTS, check_api, propose_api
from shirushi.live import unique_decisions, verify_previous
from shirushi.refresh import merge
from shirushi.snapshots import SnapshotStore, digest
from shirushi_eval.financial_coverage import compare_accounts, reference_accounts
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'
WHEN = '2026-10-08T08:00:00Z'


def filing(year=2025, kind='SELSKAP'):
    return {'virksomhet': {'organisasjonsnummer': SUBJECT}, 'regnskapstype': kind,
            'valuta': 'USD', 'regnskapsperiode': {'fraDato': f'{year}-01-01', 'tilDato': f'{year}-12-31'},
            'resultatregnskapResultat': {'aarsresultat': -3, 'ordinaertResultatFoerSkattekostnad': -2,
                                       'driftsresultat': {'driftsresultat': -1,
                                                         'driftsinntekter': {'sumDriftsinntekter': 10}}},
            'eiendeler': {'sumEiendeler': 20},
            'egenkapitalGjeld': {'egenkapital': {'sumEgenkapital': 5},
                                'gjeldOversikt': {'sumGjeld': 15,
                                                 'kortsiktigGjeld': {'sumKortsiktigGjeld': 6},
                                                 'langsiktigGjeld': {'sumLangsiktigGjeld': 9}}}}


class FinancialCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / 'store')
        self.audit = SourceAudit(self.store.root, [SUBJECT])

    def prepare(self, body):
        raw = json.dumps(body).encode()
        url = ACCOUNTS + SUBJECT
        sid = self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': 'brreg_accounts',
                                    'source_url': url, 'effective_url': url, 'http_status': 200,
                                    'retrieved_at': WHEN, 'sha256': digest(raw), 'source_origin': 'data.brreg.no',
                                    'access_policy': 'brreg-open-data-nlod-2.0'})
        candidates = propose_api(self.store, sid)
        return sid, candidates, [check_api(self.store, c, SUBJECT) for c in candidates]

    def comparison(self, sid, decisions):
        envelope = dict(merge(None, unique_decisions(decisions), WHEN), organisation_number=SUBJECT)
        report = {'companies': [{'envelope': envelope, 'attempts': [
            {'source': 'brreg_accounts', 'status': 'checked', 'snapshot_id': sid}]}]}
        return compare_accounts([envelope], report, self.audit)

    def test_all_explicit_fields_retain_currency_and_losses(self):
        _, _, decisions = self.prepare([filing()])
        expected = {'annual_revenue': 10, 'annual_operating_profit': -1, 'annual_profit_before_tax': -2,
                    'annual_net_profit': -3, 'total_assets': 20, 'total_equity': 5, 'total_liabilities': 15,
                    'current_liabilities': 6, 'long_term_liabilities': 9}
        self.assertEqual(len(decisions), 9)
        self.assertTrue(all(d['accepted'] for d in decisions))
        self.assertEqual({d['field']: d['claim']['value']['amount'] for d in decisions}, expected)
        with patch('shirushi.api_sources.check_api', side_effect=AssertionError('Maker imported')):
            for d in decisions:
                self.assertEqual(d['claim']['value']['currency'], 'USD')
                self.audit.claim(SUBJECT, d['claim'], {d['evidence']['id']: d['evidence']})

    def test_missing_revenue_can_recover_a_financial_company_without_extra_requests(self):
        record = filing()
        record.pop('resultatregnskapResultat')
        record['eiendeler']['sumEiendeler'] = 0
        record['egenkapitalGjeld']['egenkapital']['sumEgenkapital'] = -5
        sid, _, decisions = self.prepare([record])
        result = self.comparison(sid, decisions)
        self.assertEqual(result['baseline']['covered_companies'], 0)
        self.assertEqual(result['challenger']['covered_companies'], 1)
        self.assertEqual(result['additional_covered_companies'], 1)
        self.assertEqual(result['additional_facts'], 5)
        self.assertEqual(result['additional_acquisition_requests'], 0)
        self.assertIn(0, [d['claim']['value']['amount'] for d in decisions])

    def test_null_financial_values_are_not_published_as_zero(self):
        record = filing()
        record['resultatregnskapResultat']['aarsresultat'] = None
        record['eiendeler'] = {}
        _, candidates, decisions = self.prepare([record])
        self.assertEqual(len(candidates), 7)
        self.assertNotIn('annual_net_profit', [d['field'] for d in decisions])
        self.assertNotIn('total_assets', [d['field'] for d in decisions])

    def test_boolean_string_and_excessive_integer_are_rejected_without_worker_failure(self):
        for amount in (True, '20', 10 ** 400):
            with self.subTest(amount_type=type(amount).__name__):
                record = filing()
                record['eiendeler']['sumEiendeler'] = amount
                _, _, decisions = self.prepare([record])
                asset = next(d for d in decisions if d['field'] == 'total_assets')
                self.assertFalse(asset['accepted'])
                self.assertEqual(sum(d['accepted'] for d in decisions), 8)
                _, diagnostics = reference_accounts(json.dumps([record]), SUBJECT)
                self.assertEqual(diagnostics['invalid_amounts'], 1)

    def test_every_financial_field_rejects_wrong_company(self):
        record = filing()
        record['virksomhet']['organisasjonsnummer'] = '999999999'
        _, _, decisions = self.prepare([record])
        self.assertEqual(len(decisions), 9)
        self.assertTrue(all(not d['accepted'] for d in decisions))

    def test_invalid_period_and_currency_are_rejected_by_both_checkers(self):
        for update in ({'valuta': 'usd'}, {'regnskapsperiode': {'fraDato': '20250101', 'tilDato': '20251231'}},
                       {'regnskapsperiode': {'fraDato': '2025-02-30', 'tilDato': '2025-12-31'}},
                       {'regnskapsperiode': {'fraDato': '2025-12-31', 'tilDato': '2025-01-01'}}):
            record = dict(filing(), **update)
            _, _, decisions = self.prepare([record])
            self.assertTrue(all(not d['accepted'] for d in decisions))
            reference, stats = reference_accounts(json.dumps([record]), SUBJECT)
            self.assertEqual(reference, {})
            self.assertEqual(stats['invalid_records'], 1)

    def test_unsupported_field_or_swapped_source_path_cannot_borrow_revenue_evidence(self):
        _, candidates, decisions = self.prepare([filing()])
        revenue = candidates[0]
        for field in ('annual_net_profit', 'invented_margin'):
            self.assertFalse(check_api(self.store, replace(revenue, field=field), SUBJECT)['accepted'])
        damaged = copy.deepcopy(decisions[0]['claim'])
        damaged['field'] = 'annual_net_profit'
        with self.assertRaises(ValueError):
            self.audit.claim(SUBJECT, damaged, {decisions[0]['evidence']['id']: decisions[0]['evidence']})

    def test_three_years_and_two_scopes_survive_replay_and_one_value_change(self):
        records = [filing(year, kind) for year in (2023, 2024, 2025) for kind in ('SELSKAP', 'KONSERN')]
        _, _, decisions = self.prepare(records)
        first = merge(None, decisions, WHEN)
        self.assertEqual(len(first['claims']), 54)
        same = merge(first, decisions, WHEN)
        self.assertEqual(same['changes'], [])
        records[-1]['egenkapitalGjeld']['egenkapital']['sumEgenkapital'] = 7
        _, _, changed = self.prepare(records)
        second = merge(first, changed, WHEN)
        self.assertEqual(len(second['claims']), 54)
        self.assertEqual(len(second['changes']), 1)
        self.assertEqual(second['changes'][0]['field'], 'total_equity')
        self.assertEqual(second['history'][0]['scope'], 'group_accounts')
        self.assertEqual(second['history'][0]['period']['tilDato'], '2025-12-31')
        verify_previous(self.store, dict(second, organisation_number=SUBJECT), SUBJECT)

    def test_revenue_only_previous_output_expands_without_false_changes(self):
        _, _, decisions = self.prepare([filing()])
        first = merge(None, [decisions[0]], WHEN)
        second = merge(first, decisions, WHEN)
        self.assertEqual(len(second['claims']), 9)
        self.assertEqual(second['changes'], [])
        verify_previous(self.store, second, SUBJECT)

    def test_forged_prior_financial_slot_and_context_are_rejected(self):
        _, _, decisions = self.prepare([filing()])
        first = merge(None, decisions, WHEN)
        for key, value in [('claim_id', 'f' * 64), ('family', 'people'),
                           ('period', {'fraDato': '2024-01-01', 'tilDato': '2024-12-31'})]:
            damaged = copy.deepcopy(first)
            damaged['claims'][0][key] = value
            with self.assertRaises(ValueError):
                verify_previous(self.store, damaged, SUBJECT)

    def test_boolean_money_in_forged_prior_state_or_candidate_cannot_equal_numeric_one(self):
        record = filing()
        record['eiendeler']['sumEiendeler'] = 1
        sid, candidates, decisions = self.prepare([record])
        asset = next(c for c in candidates if c.field == 'total_assets')
        value = dict(asset.value, amount=True)
        self.assertFalse(check_api(self.store, replace(asset, value=value), SUBJECT)['accepted'])
        first = merge(None, decisions, WHEN)
        damaged = copy.deepcopy(first)
        claim = next(c for c in damaged['claims'] if c['field'] == 'total_assets')
        claim['value']['amount'] = True
        with self.assertRaises(ValueError):
            verify_previous(self.store, damaged, SUBJECT)
        with self.assertRaises(ValueError):
            self.audit.claim(SUBJECT, claim, {e['id']: e for e in damaged['evidence']})
        fake = next(d for d in decisions if d['field'] == 'total_assets')
        fake = copy.deepcopy(fake)
        fake['claim']['value']['amount'] = True
        comparison = self.comparison(sid, [fake])
        self.assertEqual(comparison['unsupported_publications'], 1)

    def test_reference_enumeration_detects_an_extraction_miss(self):
        sid, _, decisions = self.prepare([filing()])
        with patch('shirushi.api_sources.propose_api', side_effect=AssertionError('Maker imported')):
            result = self.comparison(sid, decisions[:-1])
        self.assertEqual(result['missing_source_facts'], 1)
        self.assertEqual(result['fields']['long_term_liabilities']['matched_facts'], 0)
        self.assertEqual(result['unsupported_publications'], 0)

    def test_conflicting_currency_or_value_abstains_per_slot(self):
        for change in ('currency', 'amount'):
            records = [filing(), filing()]
            if change == 'currency':
                records[-1]['valuta'] = 'NOK'
            else:
                records[-1]['eiendeler']['sumEiendeler'] = 21
            sid, _, decisions = self.prepare(records)
            result = self.comparison(sid, decisions)
            self.assertEqual(result['unsupported_publications'], 0)
            self.assertEqual(result['missing_source_facts'], 0)
            self.assertEqual(result['reference_diagnostics']['conflicting_slots'], 9 if change == 'currency' else 1)

    def test_unacquired_accounts_remain_unknown_in_reference(self):
        envelope = {'organisation_number': SUBJECT, 'claims': []}
        report = {'companies': [{'envelope': envelope, 'attempts': [
            {'source': 'brreg_accounts', 'status': 'failed', 'availability': 'blocked'}]}]}
        result = compare_accounts([envelope], report, self.audit)
        self.assertEqual(result['unacquired_source_companies'], 1)
        self.assertEqual(result['reference_facts'], 0)
        self.assertIsNone(result['challenger']['company_coverage'])


if __name__ == '__main__':
    unittest.main()
