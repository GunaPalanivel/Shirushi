"""Collect a declared, small official-source cache for development only."""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise urllib.error.HTTPError(request.full_url, code, 'Redirect refused', headers, response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organisations', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.organisations.read_text(encoding='utf-8').splitlines() if line.strip()]
    subjects = [r['organisation_number'] for r in records]
    if not 1 <= len(subjects) <= 20 or len(subjects) != len(set(subjects)):
        raise ValueError('Collector accepts a unique development pilot of at most 20')
    if any(not isinstance(s, str) or len(s) != 9 or not s.isascii() or not s.isdecimal() for s in subjects):
        raise ValueError('Invalid exact identity')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    opener = urllib.request.build_opener(NoRedirect)
    receipts, last_start = [], 0
    started = time.monotonic()
    for subject in subjects:
        for kind, url in [('brreg_roles_snapshot', f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'),
                          ('brreg_accounts_reference', f'https://data.brreg.no/regnskapsregisteret/regnskap/{subject}')]:
            delay = max(0, 2.1 - (time.monotonic() - last_start))
            time.sleep(delay)
            last_start = time.monotonic()
            receipt = {'organisation_number': subject, 'source_class': kind, 'source_url': url,
                       'access_policy': 'brreg-open-data-nlod-2.0',
                       'terms_url': 'https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html',
                       'acquisition_method': 'development-cache HTTPS GET; not an agent-run request',
                       'collector_spacing_seconds': 2.1, 'requests': 1}
            try:
                if time.monotonic() - started > 300:
                    raise TimeoutError('Collection budget exhausted')
                with opener.open(urllib.request.Request(url, headers={'Accept': 'application/json'}), timeout=10) as response:
                    body = response.read(5 * 1024 * 1024 + 1)
                    if len(body) > 5 * 1024 * 1024:
                        raise ValueError('Source exceeds declared byte limit')
                    receipt.update(http_status=response.status, effective_url=response.geturl(),
                                   retrieved_at=datetime.now(timezone.utc).isoformat())
                filename = subject + ('-roles.json' if kind == 'brreg_roles_snapshot' else '-accounts.json')
                (args.output_dir / filename).write_bytes(body)
                receipt.update(path=filename, sha256=hashlib.sha256(body).hexdigest(), status='captured')
            except Exception as exc:
                receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}',
                               retrieved_at=datetime.now(timezone.utc).isoformat())
            receipts.append(receipt)
            print(json.dumps({'organisation_number': subject, 'source': kind, 'status': receipt['status']}), flush=True)
    (args.output_dir / 'acquisition-manifest.json').write_text(json.dumps(receipts, indent=2) + '\n', encoding='utf-8')
    roles = [r for r in receipts if r['source_class'] == 'brreg_roles_snapshot' and r['status'] == 'captured']
    (args.output_dir / 'roles-manifest.json').write_text(json.dumps(roles, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
