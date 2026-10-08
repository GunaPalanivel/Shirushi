"""Bounded untrusted discovery leads; search content is never evidence."""
import os
import json
import re
import threading
import unicodedata
from urllib.parse import urlencode, urlsplit

from .contracts import load, loads, timestamp
from .fetch import BRAVE_REQUEST_COST_USD, SourceUnavailable, safe_url
from .snapshots import digest

ENDPOINT = 'https://api.search.brave.com/res/v1/web/search'
COST_PER_ATTEMPT_USD = BRAVE_REQUEST_COST_USD  # No credit assumptions.


def legal_name_candidates(name):
    """Two domain hypotheses from a verified legal name, never ownership proof."""
    if not isinstance(name, str):
        return []
    words = re.findall(r'\w+', name.casefold())
    while words and words[-1] in {'as', 'asa', 'ans', 'da', 'enk', 'nuf', 'sa', 'ba'}:
        words.pop()
    stem = ''.join(words).replace('ø', 'o').replace('æ', 'ae').replace('å', 'a')
    stem = ''.join(c for c in unicodedata.normalize('NFKD', stem) if c.isascii() and c.isalnum())
    if not 3 <= len(stem) <= 63 or stem.isdecimal():
        return []
    return ['https://' + stem + suffix + '/' for suffix in ('.com', '.no')]


class LegalNameDiscovery:
    """No search service or credentials; publication still requires exact proof."""
    def __init__(self):
        self.diagnostics = {}

    def candidates(self, subject, entity=None):
        if re.fullmatch('[0-9]{9}', subject) is None:
            raise ValueError('Exact organisation number required')
        leads = legal_name_candidates((entity or {}).get('navn'))
        self.diagnostics[subject] = [{'source': 'legal_name_hypothesis', 'candidate_urls': leads}]
        return leads


def access_receipt(path):
    receipt = load(path)
    required = {'provider', 'terms_url', 'plan_rights_source', 'reviewed_at',
                'permits_company_discovery_and_evaluation', 'request_interval_seconds',
                'max_candidates', 'max_queries_per_company'}
    terms = {'brave': 'https://api-dashboard.search.brave.com/documentation/resources/terms-of-service',
             'anysearch': 'https://anysearch.com/docs/auth'}
    if (not isinstance(receipt, dict) or set(receipt) != required or receipt.get('provider') not in terms
            or receipt['terms_url'] != terms[receipt['provider']]
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

    def candidates(self, subject, entity=None):
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


class AnySearchDiscovery:
    """Documented anonymous discovery; source bodies remain the only evidence."""
    def __init__(self, fetcher, receipt):
        self.fetcher, self.receipt = fetcher, receipt
        self.error, self.lock = None, threading.Lock()
        self.diagnostics = {}
        fetcher.budget.set_host_interval('api.anysearch.com', receipt['request_interval_seconds'])

    def candidates(self, subject, entity=None):
        if re.fullmatch('[0-9]{9}', subject) is None:
            raise ValueError('Exact organisation number required')
        while not self.lock.acquire(timeout=0.05):
            self.fetcher.budget.remaining()
        try:
            self.diagnostics[subject] = []
            if self.error:
                raise SourceUnavailable(self.error, 'blocked')
            leads = self._candidates(subject, entity)
            return self._supplement(subject, entity, leads) if leads else self._fallback(subject, entity, 'No usable search candidate')
        except SourceUnavailable as exc:
            if exc.availability == 'blocked':
                self.error = 'Anonymous discovery unavailable: ' + str(exc)
            leads = self._fallback(subject, entity, str(exc))
            if leads:
                return leads
            raise
        finally:
            self.lock.release()

    def _supplement(self, subject, entity, leads):
        # Nonempty newsroom/reseller search results are not useful identity
        # leads. Include bounded hypotheses before spending the HTML budget.
        name = (entity or {}).get('navn', '')
        words = [w for w in re.findall(r'\w+', name.casefold()) if len(w) >= 3 and w not in {'as', 'asa'}]
        combined, hosts, added = list(leads), {urlsplit(u).hostname.removeprefix('www.') for u in leads}, []
        for url in legal_name_candidates(name):
            host = urlsplit(url).hostname.removeprefix('www.')
            if host not in hosts:
                combined.append(url); added.append(url); hosts.add(host)
        if added:
            self.diagnostics[subject].append({'source': 'legal_name_hypothesis',
                'reason': 'Bounded candidate supplementation', 'candidate_urls': added})
        def rank(url):
            parts = urlsplit(url)
            return (not any(word in parts.hostname.casefold() for word in words),
                    parts.hostname.startswith(('newsroom.', 'news.', 'blog.')),
                    not bool(re.search(r'vilk|terms|legal|jurid', parts.path, re.I)))
        combined.sort(key=rank)
        return combined[:self.receipt['max_candidates']]

    def _fallback(self, subject, entity, reason):
        leads = legal_name_candidates((entity or {}).get('navn'))[:self.receipt['max_candidates']]
        self.diagnostics[subject].append({'source': 'legal_name_hypothesis', 'reason': reason,
                                         'candidate_urls': leads})
        return leads

    def _candidates(self, subject, entity=None):
        if re.fullmatch('[0-9]{9}', subject) is None:
            raise ValueError('Exact organisation number required')
        name = (entity or {}).get('navn', '')
        spaced = ' '.join(subject[i:i+3] for i in range(0, 9, 3))
        queries = (['"' + name + '" "' + spaced + '"', '"' + name + '" official website Norway'] if name
                   else ['"' + subject + '" website', '"' + subject + '"'])
        candidates, hosts = [], set()
        self.diagnostics[subject] = []
        directories = {'proff.no', 'purehelp.no', 'virksomhet.brreg.no', 'firmalisten.no', 'firmadatabasen.no',
                       'regnskapsbasen.no', 'biztrac.no', 'soom.no', 'gulesider.no', '1881.no',
                       'tracxn.com', 'yra.no', 'vexter.no', 'facebook.com', 'linkedin.com'}
        words = [word for word in re.findall(r'\w+', name.casefold()) if len(word) >= 3 and word not in {'as', 'asa'}]
        for query_index, query in enumerate(queries[:self.receipt['max_queries_per_company']]):
            if query_index == 1:
                likely_host = next((urlsplit(candidate).hostname for candidate in candidates
                    if any(word in urlsplit(candidate).hostname.casefold() for word in words)
                    and not urlsplit(candidate).hostname.startswith(('newsroom.', 'news.', 'blog.'))), None)
                if likely_host:
                    # First-party host is only a search lead. Exact org proof is
                    # still required, including when the first page is foreign.
                    query = 'site:' + likely_host.removeprefix('www.') + ' "' + spaced + '"'
            payload = json.dumps({'query': query, 'max_results': 10, 'zone': 'intl', 'format': 'json'}).encode()
            raw, _ = self.fetcher.get('https://api.anysearch.com/v1/search', {'api.anysearch.com'}, request_body=payload)
            body = loads(raw)
            if not isinstance(body, dict):
                raise SourceUnavailable('Invalid discovery response')
            if body.get('code') != 0:
                raise SourceUnavailable('Anonymous discovery quota or provider error', 'blocked')
            data = body.get('data')
            if not isinstance(data, dict):
                raise SourceUnavailable('Invalid discovery response')
            results = data.get('results', [])
            if not isinstance(results, list):
                raise SourceUnavailable('Invalid discovery response')
            self.diagnostics[subject].append({'query': query,
                'request_id': body.get('request_id') if isinstance(body.get('request_id'), str) else None,
                'result_count': len(results), 'candidate_urls': []})
            for row in results[:10]:
                try:
                    url = safe_url(row.get('url')); host = urlsplit(url).hostname
                except (ValueError, AttributeError):
                    continue
                self.diagnostics[subject][-1]['candidate_urls'].append(url)
                if (any(host == domain or host.endswith('.' + domain) for domain in directories)
                        or re.search(r'\.(?:pdf|jpg|jpeg|png|zip)$', urlsplit(url).path, re.I)):
                    continue
                if host in hosts:
                    # A later exact-org query often returns an unlinked legal
                    # page on a host already found by its company name.
                    if re.search(r'vilk|terms|legal|jurid', urlsplit(url).path, re.I):
                        index = next(i for i, old in enumerate(candidates) if urlsplit(old).hostname == host)
                        candidates[index] = url
                    continue
                candidates.append(url); hosts.add(host)
        def rank(url):
            parts = urlsplit(url)
            return (not any(word in parts.hostname.casefold() for word in words),
                    not bool(re.search(r'vilk|terms|legal|jurid', parts.path, re.I)))
        candidates.sort(key=rank)
        return candidates[:self.receipt['max_candidates']]
