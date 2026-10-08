"""Bounded HTTPS acquisition with DNS pinning and whole-run accounting."""
import http.client
import ipaddress
import math
import socket
import ssl
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = 'Shirushi/0.1'
BRAVE_REQUEST_COST_USD = 0.005


def re_token(value):
    return 1 <= len(value) <= 1000 and all(33 <= ord(c) <= 126 for c in value)


class BudgetExceeded(TimeoutError):
    pass


class SourceUnavailable(ValueError):
    def __init__(self, reason, availability='failed'):
        super().__init__(reason)
        self.availability = availability


def safe_url(url, allowed_hosts=None):
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise SourceUnavailable('Invalid URL')
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').encode('idna').decode('ascii').lower()
        if (parts.scheme != 'https' or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or host.endswith('.') or '\\' in url):
            raise ValueError('Only credential-free HTTPS on port 443 is allowed')
        if allowed_hosts is not None and host not in allowed_hosts:
            raise ValueError('Redirect or URL escapes the permitted host scope')
        return urlunsplit(('https', host, parts.path or '/', parts.query, ''))
    except (ValueError, UnicodeError) as exc:
        raise SourceUnavailable(str(exc), 'blocked') from exc


def website_candidate(value):
    """Upgrade registry HTTP hints for HTTPS discovery; never fetch HTTP."""
    if not isinstance(value, str):
        raise SourceUnavailable('Invalid website lead')
    if value.startswith('http://'):
        value = 'https://' + value[7:]
    return safe_url(value if '://' in value else 'https://' + value)


def website_hosts(host):
    # Only the conventional www alias, never arbitrary subdomains or parents.
    return {host, host[4:] if host.startswith('www.') else 'www.' + host}


def public_addresses(host):
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    def permitted(address):
        value = ipaddress.ip_address(address)
        return value.is_global and not value.is_multicast and not value.is_reserved and not getattr(value, 'is_site_local', False)
    if not addresses or any(not permitted(a) for a in addresses):
        raise SourceUnavailable('Private, special or mixed DNS destination refused', 'blocked')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class Budget:
    """Atomic whole-run ledger; condition waits release the scheduler lock."""
    def __init__(self, config, deadline, callback=None):
        self.config, self.deadline, self.callback = config, deadline, callback
        self.requests = self.bytes = 0
        self.reserved_bytes = 0
        self.cost = 0.0
        self.last_start, self.host_intervals, self.active = {}, {}, {}
        self.condition = threading.Condition(threading.RLock())
        self.cancelled = threading.Event()
        self.local = threading.local()
        self.peak_active = 0
        self.in_network = 0

    def emit(self):
        with self.condition:
            result = {'requests': self.requests, 'response_bytes': self.bytes,
                      'reserved_response_bytes': self.reserved_bytes,
                      'third_party_cost_usd': self.cost, 'peak_network_requests': self.peak_active}
            if self.callback:
                self.callback(result)
            return result

    def remaining(self):
        left = self.deadline - time.monotonic()
        if self.cancelled.is_set() or left <= 0:
            raise BudgetExceeded('Cancelled or wall-time budget exhausted')
        return left

    def cancel(self):
        self.cancelled.set()
        with self.condition:
            self.condition.notify_all()

    def set_host_interval(self, host, seconds):
        with self.condition:
            self.host_intervals[host] = max(seconds, self.host_intervals.get(host, 0))
            self.condition.notify_all()

    def wait(self, seconds):
        if seconds >= self.remaining():
            raise BudgetExceeded('Wait would exhaust time budget')
        if self.cancelled.wait(seconds):
            raise BudgetExceeded('Cancelled')
        self.remaining()

    def start(self, host, cost=0.0):
        with self.condition:
            while True:
                self.remaining()
                if self.requests >= self.config['request_budget']:
                    raise BudgetExceeded('Request budget exhausted')
                if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
                    raise ValueError('Invalid paid request charge')
                if self.cost + cost > self.config['third_party_cost_usd'] + 1e-12:
                    raise BudgetExceeded('Paid request budget exhausted')
                delay = max(0, max(self.config['min_host_interval_seconds'], self.host_intervals.get(host, 0)) -
                            (time.monotonic() - self.last_start.get(host, 0)))
                if not delay:
                    break
                if delay >= self.remaining():
                    raise BudgetExceeded('Host spacing would exhaust time budget')
                self.condition.wait(delay)
            self.requests += 1
            self.cost += cost
            self.local.requests = getattr(self.local, 'requests', 0) + 1
            self.local.cost = getattr(self.local, 'cost', 0.0) + cost
            self.last_start[host] = time.monotonic()
            self.emit()  # Attempts, including failures, are charged before DNS/connect.
            return min(self.config['request_timeout_seconds'], self.remaining())

    @contextmanager
    def request(self, host, cost=0.0):
        with self.condition:
            while self.active.get(host, 0) >= self.config.get('per_host_concurrency', 1):
                self.condition.wait(min(0.05, self.remaining()))
            self.remaining()
            self.active[host] = self.active.get(host, 0) + 1
        entered = False
        try:
            timeout = self.start(host, cost)
            with self.condition:
                self.in_network += 1
                entered = True
                self.peak_active = max(self.peak_active, self.in_network)
            yield timeout
        finally:
            with self.condition:
                if entered:
                    self.in_network -= 1
                self.active[host] -= 1
                self.condition.notify_all()

    def consume(self, count):
        with self.condition:
            if type(count) is not int or count < 0:
                raise ValueError('Invalid byte charge')
            if count > self.config['max_total_bytes'] - self.bytes - self.reserved_bytes:
                raise BudgetExceeded('Response byte budget exhausted')
            self.bytes += count
            self.emit()

    def remaining_bytes(self):
        with self.condition:
            return self.config['max_total_bytes'] - self.bytes - self.reserved_bytes

    def reserve_read(self, limit):
        with self.condition:
            while self.remaining_bytes() <= 0:
                self.remaining()
                if not self.reserved_bytes:
                    raise BudgetExceeded('Response byte budget exhausted')
                self.condition.wait(min(0.05, self.remaining()))
            self.remaining()
            count = min(limit, self.remaining_bytes())
            self.reserved_bytes += count
            self.emit()
            return count

    def finish_read(self, reservation, count):
        with self.condition:
            if not 0 <= count <= reservation <= self.reserved_bytes:
                raise ValueError('Invalid response byte reservation')
            self.reserved_bytes -= reservation
            self.bytes += count
            self.emit()
            self.condition.notify_all()


class Fetcher:
    def __init__(self, budget, transport=None):
        self.budget = budget
        self.transport = transport or self._request
        self.external_transport = transport is not None
        self.robots = {}
        self.robots_sources = {}
        self.robots_condition = threading.Condition()
        self.robots_pending = set()

    def _request(self, url, timeout, limit, request_headers=None, request_body=None):
        parts = urlsplit(url)
        # Connect only to the validated address; TLS still verifies the hostname.
        address = public_addresses(parts.hostname)[0]
        connection = PinnedHTTPS(parts.hostname, address, timeout)
        try:
            target = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
            if parts.query:
                target += '?' + quote(parts.query, safe="%/?@!$&'()*+,;=:-._~")
            connection.request('POST' if request_body is not None else 'GET', target, body=request_body,
                               headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity',
                                        'Accept': 'application/json,text/html,text/plain',
                                        **({'Content-Type': 'application/json'} if request_body is not None else {}), **(request_headers or {})})
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            chunks, total = [], 0
            while True:
                if response.isclosed():
                    break
                reservation = self.budget.reserve_read(min(65536, limit - total + 1))
                try:
                    chunk = response.read(reservation)
                except BaseException:
                    # Conservatively charge the reserved cap on interrupted reads.
                    self.budget.finish_read(reservation, reservation)
                    raise
                self.budget.finish_read(reservation, len(chunk))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise SourceUnavailable('Response exceeds per-source byte limit')
                self.budget.remaining()
                chunks.append(chunk)
            return response.status, headers, b''.join(chunks)
        finally:
            connection.close()

    def get(self, url, allowed_hosts, robots=False, request_headers=None, cost=0.0, request_body=None):
        url = safe_url(url, allowed_hosts)
        if request_headers is not None:
            brave = (urlsplit(url).hostname == 'api.search.brave.com' and urlsplit(url).path == '/res/v1/web/search'
                     and set(request_headers) == {'X-Subscription-Token'} and cost == BRAVE_REQUEST_COST_USD)
            nav = (urlsplit(url).hostname == 'pam-stilling-feed.nav.no' and urlsplit(url).path.startswith('/api/v1/')
                   and set(request_headers) <= {'Authorization', 'If-Modified-Since'} and 'Authorization' in request_headers
                   and isinstance(request_headers['Authorization'], str)
                   and request_headers['Authorization'].startswith('Bearer ') and cost == 0)
            if (not (brave or nav) or robots or request_body is not None
                    or any(not isinstance(v, str) or not re_token(v.replace(' ', '_')) for v in request_headers.values())):
                raise SourceUnavailable('Authenticated request scope refused', 'blocked')
        if request_body is not None and (urlsplit(url).hostname != 'api.anysearch.com'
                or urlsplit(url).path != '/v1/search' or request_headers is not None or robots or cost != 0
                or not isinstance(request_body, bytes) or len(request_body) > 8192):
            raise SourceUnavailable('POST request scope refused', 'blocked')
        if robots:
            self.check_robots(url, allowed_hosts)
        original = url
        redirect_chain = []
        limit = self.budget.config['max_response_bytes']
        redirects = retries = 0
        while True:
            try:
                with self.budget.request(urlsplit(url).hostname, cost) as timeout:
                    args = (url, timeout, limit)
                    status, headers, raw = (self.transport(*args, None, request_body) if request_body is not None else
                                           self.transport(*args, request_headers) if request_headers is not None
                                            else self.transport(*args))
                    if self.external_transport:
                        self.budget.consume(len(raw))
                    if len(raw) > limit:
                        raise SourceUnavailable('Response exceeds per-source byte limit')
            except BudgetExceeded:
                raise
            except (OSError, http.client.HTTPException) as exc:
                if retries >= self.budget.config['max_retries']:
                    reason = type(exc).__name__ if request_headers is not None else type(exc).__name__ + ': ' + str(exc)
                    raise SourceUnavailable(reason) from None
                retries += 1
                continue
            if headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
                raise SourceUnavailable('Unsupported compressed response')
            if status in (301, 302, 303, 307, 308):
                if request_headers is not None or request_body is not None:
                    raise SourceUnavailable('Authenticated redirects refused', 'blocked')
                if redirects >= 3 or not headers.get('location'):
                    raise SourceUnavailable('Redirect bound exceeded', 'blocked')
                target = safe_url(urljoin(url, headers['location']), allowed_hosts)
                redirect_chain.append({'from': url, 'to': target, 'http_status': status})
                url = target
                if robots:
                    self.check_robots(url, allowed_hosts)
                redirects += 1
                continue
            if status in (429, 500, 502, 503, 504) and retries < self.budget.config['max_retries']:
                delay = headers.get('retry-after', '1')
                wait = float(delay) if delay.isdecimal() else 1.0
                if wait > 5 or wait >= self.budget.remaining():
                    raise SourceUnavailable('Retry-After exceeds retry allowance', 'blocked')
                self.budget.wait(wait)
                retries += 1
                continue
            if status != 200:
                state = 'not_available' if status == 404 else 'blocked' if status in (401, 402, 403, 429) else 'failed'
                error = SourceUnavailable(f'HTTP {status}', state)
                error.response = (raw, {'source_url': original, 'effective_url': url, 'http_status': status,
                    'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'content_type': headers.get('content-type', ''), 'source_origin': urlsplit(url).hostname})
                raise error
            receipt = {'source_url': original, 'effective_url': url, 'http_status': status,
                         'retrieved_at': datetime.now(timezone.utc).isoformat(),
                         'content_type': headers.get('content-type', ''), 'source_origin': urlsplit(url).hostname,
                         'redirect_chain': redirect_chain}
            if robots:
                with self.robots_condition:
                    receipt['robots_response'] = self.robots_sources['https://' + urlsplit(url).netloc]
            return raw, receipt

    def advertised_sitemaps(self, url, allowed_hosts):
        """Return observed same-host metadata leads, after establishing robots."""
        self.check_robots(url, allowed_hosts)
        origin = 'https://' + urlsplit(url).netloc
        result = []
        with self.robots_condition:
            leads = self.robots[origin].site_maps() or []
        for lead in leads:
            try:
                candidate = safe_url(lead, {urlsplit(url).hostname})
            except SourceUnavailable:
                continue
            if candidate not in result:
                result.append(candidate)
        return result[:2]

    def check_robots(self, url, allowed_hosts):
        parts = urlsplit(url)
        origin = 'https://' + parts.netloc
        with self.robots_condition:
            while origin in self.robots_pending:
                self.robots_condition.wait(min(0.05, self.budget.remaining()))
            parser = self.robots.get(origin)
            if parser is None:
                self.robots_pending.add(origin)
        if parser is None:
            try:
                parser = RobotFileParser(origin + '/robots.txt')
                try:
                    raw, receipt = self.get(origin + '/robots.txt', allowed_hosts)
                    if len(raw) > 65536:
                        raise SourceUnavailable('Robots response exceeds policy bound', 'blocked')
                    parser.parse(raw.decode('utf-8').splitlines())
                    delay = parser.crawl_delay(USER_AGENT)
                    if delay:
                        self.budget.set_host_interval(parts.hostname, delay)
                except SourceUnavailable as exc:
                    if exc.availability != 'not_available':
                        raise SourceUnavailable('Robots access could not be established', 'blocked') from exc
                    raw, receipt = exc.response
                    parser.parse([])
                with self.robots_condition:
                    self.robots[origin] = parser
                    self.robots_sources[origin] = (raw, receipt)
            finally:
                with self.robots_condition:
                    self.robots_pending.remove(origin)
                    self.robots_condition.notify_all()
        if not parser.can_fetch(USER_AGENT, url):
            raise SourceUnavailable('Robots disallows URL', 'blocked')
