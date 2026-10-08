"""Frozen identity, source forgery, cutoff and external wire counterexamples."""
import copy
import csv
import gzip
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.batch import envelope
from shirushi.contracts import ROOT, load
from shirushi.evidence import EvidenceChecker
from shirushi.extraction import Candidate, extract
from shirushi.identity import legal_anchor
from shirushi.live import verify_previous, worker
from shirushi.official import read_inputs, shards
from shirushi.refresh import merge
from shirushi.registry import acquire_batch
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi.wire import convert
from shirushi_eval.support import SourceAudit
from shirushi_eval.wire import internal_records, validate_public_contract

SUBJECT = '923609016'
NAME = 'Example Pumps AS'
WHEN = '2026-10-08T08:00:00Z'


class Pipe:
    def __init__(self):
        self.messages = []
    def send(self, message):
        self.messages.append(message)
    def close(self):
        pass


class OfficialBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SnapshotStore(self.root / 'snapshots')

    def frozen(self, rows=None, csv_source=False, compressed=True):
        rows = rows or [{'organisation_number': SUBJECT, 'name': NAME, 'employees': 0}]
        if csv_source:
            body = io.StringIO(newline='')
            writer = csv.DictWriter(body, ['organisasjonsnummer', 'navn', 'antallAnsatte', 'hjemmeside'], delimiter=';')
            writer.writeheader()
            for row in rows:
                writer.writerow({'organisasjonsnummer': row['organisation_number'], 'navn': row['name'],
                    'antallAnsatte': row.get('employees', ''), 'hjemmeside': 'example.com'})
            raw = body.getvalue().encode()
        else:
            raw = b''.join((json.dumps(row) + '\n').encode() for row in rows)
        archive = gzip.compress(raw, mtime=0) if compressed else raw
        path = self.root / ('registry.' + ('csv' if csv_source else 'jsonl') + ('.gz' if compressed else ''))
        path.write_bytes(archive)
        receipt = {'source_class': 'frozen_registry', 'source_url': 'https://example.org/frozen',
                   'retrieved_at': WHEN, 'sha256': digest(archive), 'uncompressed_sha256': digest(raw),
                   'dataset_format': 'csv' if csv_source else 'jsonl'}
        receipt_path = self.root / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        ids = acquire_batch(path, receipt, [r['organisation_number'] for r in rows], self.store, time.monotonic() + 10)
        return path, receipt_path, ids

    def check(self, sid):
        checker = EvidenceChecker(self.store, [SUBJECT])
        return [checker.check(c, SUBJECT) for c in extract(self.store, sid)]

    def audit(self, decisions):
        for decision in decisions:
            if decision['accepted']:
                SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, decision['claim'],
                    {decision['evidence']['id']: decision['evidence']})

    def test_csv_zero_missing_and_multiline_name_have_full_archive_proof(self):
        for compressed in (False, True):
            _, _, ids = self.frozen(csv_source=True, compressed=compressed,
                                   rows=[{'organisation_number': SUBJECT, 'name': 'Example\nPumps AS', 'employees': 0}])
            decisions = self.check(ids[SUBJECT])
            zero = next(d for d in decisions if d['field'] == 'registered_employees')
            self.assertTrue(zero['accepted'])
            self.assertEqual(zero['claim']['value'], 0)
            self.assertEqual(zero['evidence']['claim_span'], '"0"')
            self.audit(decisions)
        _, _, ids = self.frozen(csv_source=True, rows=[{'organisation_number': SUBJECT, 'name': NAME}])
        missing = next(d for d in self.check(ids[SUBJECT]) if d['field'] == 'registered_employees')
        self.assertFalse(missing['accepted'])
        self.assertEqual(missing['reason'], 'absent_in_frozen_row')

    def test_csv_header_sniff_cannot_disable_escaped_quotes_in_company_values(self):
        name = 'Example "Pumps; Valves" AS'
        _, _, ids = self.frozen(csv_source=True, rows=[{'organisation_number': SUBJECT, 'name': name, 'employees': 0}])
        decisions = self.check(ids[SUBJECT])
        self.assertEqual(next(d['claim']['value'] for d in decisions if d['field'] == 'legal_name'), name)
        self.audit(decisions)

    def test_csv_forged_projection_wrong_row_and_parent_are_rejected_independently(self):
        _, _, ids = self.frozen(csv_source=True)
        sid = ids[SUBJECT]
        raw, receipt = self.store.open(sid)
        checker = EvidenceChecker(self.store, [SUBJECT])
        self.assertFalse(checker.check(Candidate(SUBJECT, 'registered_employees', 17, sid), SUBJECT)['accepted'])
        row = json.loads(raw)
        row['navn'] = 'Other AS'
        forged = self.store.save(json.dumps(row).encode(), receipt)
        self.assertFalse(checker.check(Candidate(SUBJECT, 'legal_name', 'Other AS', forged), SUBJECT)['accepted'])
        with self.assertRaises(ValueError):
            legal_anchor(self.store, forged, SUBJECT)
        valid = next(d for d in self.check(sid) if d['field'] == 'registered_employees')
        attacked = copy.deepcopy(valid)
        attacked['claim']['value'] = 17
        with self.assertRaises(ValueError):
            self.audit([attacked])
        self.store.path('objects', receipt['parent_sha256']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.audit([valid])

    def test_frozen_identity_survives_entity_outage_without_entity_request(self):
        registry, receipt, _ = self.frozen(csv_source=True)
        config = load(ROOT / 'configs/shard-validation.json')
        config['enabled_sources'] = ['frozen_registry', 'brreg_accounts']
        pipe = Pipe()
        job = {'subjects': [SUBJECT], 'registry': registry, 'registry_receipt': receipt,
            'store': self.store.root, 'config': config, 'deadline': time.monotonic() + 20,
            'run_id': 'outage', 'started_at': WHEN, 'previous': {}, 'discovery': None, 'cutoff': WHEN}
        from shirushi.fetch import SourceUnavailable
        with patch('shirushi.live.Fetcher.get', side_effect=SourceUnavailable('HTTP 503')) as fetch:
            worker(pipe, job)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('regnskapsregisteret', fetch.call_args.args[0])
        result = next(body for kind, _, body in pipe.messages if kind == 'result')['envelope']
        self.assertEqual(result['run']['terminal_status'], 'completed')
        self.assertEqual(next(c['value'] for c in result['claims'] if c['field'] == 'legal_name'), NAME)
        self.assertTrue(all(o['status'] == 'unknown' for o in result['opportunities']))
        self.audit([d for kind, _, body in pipe.messages if kind == 'result' for d in body['decisions']])

    def page(self, sid, cutoff=WHEN):
        raw = ('<footer>Copyright ' + NAME + '. Org.nr. 923 609 016</footer>'
               '<p>Example Pumps AS produces industrial pumps.</p>'
               '<p>On 2026-10-07, Example Pumps AS opened a factory.</p>').encode()
        receipt = {'organisation_number': SUBJECT, 'source_class': 'company_owned',
            'source_url': 'https://example.com/', 'effective_url': 'https://example.com/', 'retrieved_at': WHEN,
            'http_status': 200, 'sha256': digest(raw), 'source_origin': 'example.com', 'declared_host': 'example.com',
            'robots_checked': True, 'ownership_anchor_snapshot_id': sid, 'evaluation_cutoff': cutoff}
        return self.store.save(raw, receipt)

    def test_frozen_web_source_chain_and_cutoff_are_checked_independently(self):
        _, _, ids = self.frozen(csv_source=True)
        recent = check_web(self.store, SUBJECT, self.page(ids[SUBJECT]))
        self.assertIn('public_activity', [d['field'] for d in recent])
        self.audit(recent)
        before = check_web(self.store, SUBJECT, self.page(ids[SUBJECT], '2026-10-06T08:00:00Z'))
        self.assertNotIn('public_activity', [d['field'] for d in before])
        self.assertIn('verified_website', [d['field'] for d in before])
        self.audit(before)
        with self.assertRaises(ValueError):
            check_web(self.store, SUBJECT, self.page(ids[SUBJECT], '2026-10-09T08:00:00Z'))

    def test_wire_alias_replay_is_lossless_and_source_checked(self):
        _, _, ids = self.frozen(csv_source=True)
        decisions = self.check(ids[SUBJECT]) + check_web(self.store, SUBJECT, self.page(ids[SUBJECT]))
        prior = envelope(SUBJECT, 'first', WHEN, decisions)
        wire = convert([prior])
        self.assertIn('official_website', [c['field'] for c in wire[0]['claims']])
        self.assertEqual(validate_public_contract([SUBJECT], wire), [])
        restored = internal_records(wire)[0]
        self.assertEqual(restored, prior)
        verify_previous(self.store, restored, SUBJECT)
        replay = merge(restored, decisions, WHEN)
        self.assertEqual(replay['changes'], [])
        self.assertEqual(replay['history'], [])
        self.assertEqual(replay['evidence'], prior['evidence'])
        self.assertTrue(validate_public_contract([SUBJECT, SUBJECT], wire))

    def test_growing_input_partition_and_strict_identity(self):
        for count in (1, 100, 101, 300, 1100):
            records = [{'organisation_number': str(123450000 + i)} for i in range(count)]
            partition = shards(records)
            self.assertEqual([r for shard in partition for r in shard], records)
            self.assertTrue(all(len(shard) <= 100 for shard in partition))
        path = self.root / 'input.txt'
        path.write_text(SUBJECT + '\n')
        self.assertEqual(read_inputs(path)[1], [SUBJECT])
        path.write_text('NO ' + SUBJECT)
        with self.assertRaises(ValueError):
            read_inputs(path)
        path.write_text(SUBJECT + '\n' + SUBJECT)
        with self.assertRaises(ValueError):
            read_inputs(path)

    def test_snapshot_disk_budget_counts_new_bytes_and_preserves_content(self):
        with patch.dict(os.environ, {'SHIRUSHI_STORE_BYTE_LIMIT': '5'}):
            store = SnapshotStore(self.root / 'bounded')
            key = store.put('objects', b'12345')
            self.assertEqual(store.put('objects', b'12345'), key)
            with self.assertRaisesRegex(ValueError, 'byte limit exhausted'):
                store.put('objects', b'6')
            self.assertEqual(store.read('objects', key), b'12345')

    def test_workplace_name_lead_recovers_job_but_cannot_bypass_wrong_parent(self):
        from shirushi.nav_jobs import NavFeed, HOST, SUBUNIT
        from shirushi.fetch import Budget, Fetcher
        uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        url = 'https://' + HOST + '/api/v1/feedentry/' + uuid
        employer = '999888777'
        for parent, expected in [(SUBJECT, 1), ('111222333', 0)]:
            config = load(ROOT / 'configs/shard-validation.json')
            budget = Budget(config, time.monotonic() + 10)
            def transport(request_url, *_):
                if request_url == url:
                    body = {'status': 'ACTIVE', 'ad_content': {'employer': {'orgnr': employer}}}
                elif request_url == SUBUNIT + employer:
                    body = {'organisasjonsnummer': employer, 'overordnetEnhet': parent}
                else:
                    raise AssertionError('Unexpected retrieval')
                return 200, {'content-type': 'application/json'}, json.dumps(body).encode()
            feed = NavFeed(Fetcher(budget, transport))
            feed.index = {'pump shop oslo': [url]}
            feed.token = 'public'
            entity = {'navn': NAME}
            self.assertEqual(feed.for_company(SUBJECT, entity)[0], [])
            pages, _ = feed.for_company(SUBJECT, entity, ['Pump Shop Oslo'])
            self.assertEqual(len(pages), expected)
            self.assertEqual(budget.requests, 2)

    def test_email_domain_is_only_a_lead_and_generic_provider_is_skipped(self):
        from shirushi.live import acquire_website
        class Fetch:
            def __init__(self, owner):
                self.urls = []
                self.owner = owner
            def get(self, url, *_args, **_kw):
                self.urls.append(url)
                raw = ('<footer>Copyright ' + self.owner + '. Org.nr. ' +
                       (SUBJECT if self.owner == NAME else '111222333') + '</footer>').encode()
                return raw, {'effective_url': url, 'content_type': 'text/html'}
        for owner, supported in [(NAME, True), ('Accountant AS', False)]:
            fetch = Fetch(owner)
            pages, _, funnel = acquire_website(fetch, SUBJECT, {'navn': NAME, 'epostadresse': 'hello@pump-brand.no'}, None, 6)
            self.assertEqual(fetch.urls, ['https://pump-brand.no/'])
            self.assertEqual(bool(any(b'923609016' in raw for raw, _ in pages)), supported)
            self.assertLessEqual(funnel['candidate_pages_retrieved'], 6)
        fetch = Fetch(NAME)
        self.assertEqual(acquire_website(fetch, SUBJECT, {'navn': NAME, 'epostadresse': 'hello@gmail.com'}, None, 6)[0], [])
        self.assertEqual(fetch.urls, [])

    def test_csv_explicit_unregistered_employee_zero_is_unknown(self):
        _, _, ids = self.frozen(csv_source=True)
        # Construct a genuine source archive, rather than forging a selected row.
        path = self.root / 'employees.csv'
        raw = ('organisasjonsnummer;navn;antallAnsatte;harRegistrertAntallAnsatte\n' +
               SUBJECT + ';' + NAME + ';0;false\n').encode()
        path.write_bytes(raw)
        receipt = {'source_class': 'frozen_registry', 'dataset_format': 'csv', 'source_url': 'https://example.org/frozen',
                   'retrieved_at': WHEN, 'sha256': digest(raw), 'uncompressed_sha256': digest(raw)}
        ids = acquire_batch(path, receipt, [SUBJECT], self.store, time.monotonic() + 10)
        decisions = self.check(ids[SUBJECT])
        self.assertFalse(next(d for d in decisions if d['field'] == 'registered_employees')['accepted'])


if __name__ == '__main__':
    unittest.main()
