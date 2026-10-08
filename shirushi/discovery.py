"""One permitted discovery adapter. Search text is never retained or published."""
import os
import re
from urllib.parse import urlencode, urlsplit

from .contracts import load, loads, timestamp
from .fetch import BRAVE_REQUEST_COST_USD, SourceUnavailable, safe_url
from .snapshots import digest

ENDPOINT = 'https://api.search.brave.com/res/v1/web/search'
COST_PER_ATTEMPT_USD = BRAVE_REQUEST_COST_USD  # No credit assumptions.


def access_receipt(path):
    receipt = load(path)
    required = {'provider', 'terms_url', 'plan_rights_source', 'reviewed_at',
                'permits_company_discovery_and_evaluation', 'request_interval_seconds',
                'max_candidates', 'max_queries_per_company'}
    if (not isinstance(receipt, dict) or set(receipt) != required or receipt['provider'] != 'brave'
            or receipt['terms_url'] != 'https://api-dashboard.search.brave.com/documentation/resources/terms-of-service'
            or not isinstance(receipt['plan_rights_source'], str) or not receipt['plan_rights_source'].strip()
            or receipt['permits_company_discovery_and_evaluation'] is not True
            or type(receipt['request_interval_seconds']) not in (int, float)
            or not 0.02 <= receipt['request_interval_seconds'] <= 60
            or type(receipt['max_candidates']) is not int or not 1 <= receipt['max_candidates'] <= 3
            or type(receipt['max_queries_per_company']) is not int or not 1 <= receipt['max_queries_per_company'] <= 2):
        raise ValueError('Discovery access, account rate and plan-rights receipt required')
    timestamp(receipt['reviewed_at'])
    return dict(receipt, receipt_sha256=digest(path.read_bytes()))


class BraveDiscovery:
    def __init__(self, fetcher, receipt, token=None):
        self.fetcher, self.receipt = fetcher, receipt
        self.token = token if token is not None else os.environ.get('BRAVE_SEARCH_API_KEY')
        if not self.token:
            raise SourceUnavailable('BRAVE_SEARCH_API_KEY is unavailable', 'blocked')
        fetcher.budget.set_host_interval('api.search.brave.com', receipt['request_interval_seconds'])

    def candidates(self, subject):
        if re.fullmatch('[0-9]{9}', subject) is None:
            raise ValueError('Exact organisation number required')
        queries = ['"' + subject + '"', '"' + ' '.join(subject[i:i+3] for i in range(0, 9, 3)) + '"']
        candidates, hosts = [], set()
        for query in queries[:self.receipt['max_queries_per_company']]:
            url = ENDPOINT + '?' + urlencode({'q': query, 'count': 10, 'country': 'NO', 'spellcheck': 'false'})
            raw, _ = self.fetcher.get(url, {'api.search.brave.com'},
                                      request_headers={'X-Subscription-Token': self.token},
                                      cost=COST_PER_ATTEMPT_USD)
            results = loads(raw).get('web', {}).get('results', [])
            if not isinstance(results, list):
                raise SourceUnavailable('Invalid discovery response')
            for result in results[:10]:
                try:
                    candidate = safe_url(result.get('url'))
                except (ValueError, AttributeError):
                    continue
                host = urlsplit(candidate).hostname
                if host not in hosts:
                    candidates.append(candidate)
                    hosts.add(host)
                if len(candidates) >= self.receipt['max_candidates']:
                    return candidates
        return candidates
