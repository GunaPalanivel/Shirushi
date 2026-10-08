"""Bounded HTTPS acquisition with DNS pinning and whole-run accounting."""
import http.client
import ipaddress
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = 'Shirushi/0.1'


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
    def __init__(self, config, deadline, callback=None):
        self.config, self.deadline, self.callback = config, deadline, callback
        self.requests = self.bytes = 0
        self.last_start = {}
        self.host_intervals = {}

    def emit(self):
        result = {'requests': self.requests, 'response_bytes': self.bytes, 'third_party_cost_usd': 0}
        if self.callback:
            self.callback(result)
        return result

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise BudgetExceeded('Wall-time budget exhausted')
        return left

    def start(self, host):
        self.remaining()
        if self.requests >= self.config['request_budget']:
            raise BudgetExceeded('Request budget exhausted')
        delay = max(0, max(self.config['min_host_interval_seconds'], self.host_intervals.get(host, 0)) -
                    (time.monotonic() - self.last_start.get(host, 0)))
        if delay >= self.remaining():
            raise BudgetExceeded('Host spacing would exhaust time budget')
        if delay:
            time.sleep(delay)
        self.requests += 1
        self.last_start[host] = time.monotonic()
        self.emit()  # Charge attempts before DNS/connect, including failed ones.
        return min(self.config['request_timeout_seconds'], self.remaining())

    def consume(self, count):
        if count > self.config['max_total_bytes'] - self.bytes:
            raise BudgetExceeded('Response byte budget exhausted')
        self.bytes += count
        self.emit()
        if self.bytes > self.config['max_total_bytes']:
            raise BudgetExceeded('Response byte budget exhausted')


class Fetcher:
    def __init__(self, budget, transport=None):
        self.budget = budget
        self.transport = transport or self._request
        self.external_transport = transport is not None
        self.robots = {}

    def _request(self, url, timeout, limit):
        parts = urlsplit(url)
        # Connect only to the validated address; TLS still verifies the hostname.
        address = public_addresses(parts.hostname)[0]
        connection = PinnedHTTPS(parts.hostname, address, timeout)
        try:
            connection.request('GET', parts.path + ('?' + parts.query if parts.query else ''),
                               headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity',
                                        'Accept': 'application/json,text/html,text/plain'})
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            chunks, total = [], 0
            while True:
                left = min(limit - total + 1, self.budget.config['max_total_bytes'] - self.budget.bytes)
                if left <= 0:
                    raise BudgetExceeded('Response byte budget exhausted')
                chunk = response.read(min(65536, max(1, left)))
                if not chunk:
                    break
                total += len(chunk)
                self.budget.consume(len(chunk))
                if total > limit:
                    raise SourceUnavailable('Response exceeds per-source byte limit')
                self.budget.remaining()
                chunks.append(chunk)
            return response.status, headers, b''.join(chunks)
        finally:
            connection.close()

    def get(self, url, allowed_hosts, robots=False):
        url = safe_url(url, allowed_hosts)
        if robots:
            self.check_robots(url, allowed_hosts)
        original = url
        limit = self.budget.config['max_response_bytes']
        redirects = retries = 0
        while True:
            timeout = self.budget.start(urlsplit(url).hostname)
            try:
                status, headers, raw = self.transport(url, timeout, limit)
                if self.external_transport:
                    self.budget.consume(len(raw))
                if len(raw) > limit:
                    raise SourceUnavailable('Response exceeds per-source byte limit')
            except BudgetExceeded:
                raise
            except (OSError, http.client.HTTPException) as exc:
                if retries >= self.budget.config['max_retries']:
                    raise SourceUnavailable(type(exc).__name__ + ': ' + str(exc)) from exc
                retries += 1
                continue
            if headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
                raise SourceUnavailable('Unsupported compressed response')
            if status in (301, 302, 303, 307, 308):
                if redirects >= 3 or not headers.get('location'):
                    raise SourceUnavailable('Redirect bound exceeded', 'blocked')
                url = safe_url(urljoin(url, headers['location']), allowed_hosts)
                if robots:
                    self.check_robots(url, allowed_hosts)
                redirects += 1
                continue
            if status in (429, 500, 502, 503, 504) and retries < self.budget.config['max_retries']:
                delay = headers.get('retry-after', '1')
                wait = float(delay) if delay.isdecimal() else 1.0
                if wait > 5 or wait >= self.budget.remaining():
                    raise SourceUnavailable('Retry-After exceeds retry allowance', 'blocked')
                time.sleep(wait)
                retries += 1
                continue
            if status != 200:
                state = 'not_available' if status == 404 else 'blocked' if status in (401, 403, 429) else 'failed'
                raise SourceUnavailable(f'HTTP {status}', state)
            return raw, {'source_url': original, 'effective_url': url, 'http_status': status,
                         'retrieved_at': datetime.now(timezone.utc).isoformat(),
                         'content_type': headers.get('content-type', ''), 'source_origin': urlsplit(url).hostname}

    def check_robots(self, url, allowed_hosts):
        parts = urlsplit(url)
        origin = 'https://' + parts.netloc
        if origin not in self.robots:
            parser = RobotFileParser(origin + '/robots.txt')
            try:
                raw, _ = self.get(origin + '/robots.txt', allowed_hosts)
                parser.parse(raw.decode('utf-8').splitlines())
                delay = parser.crawl_delay(USER_AGENT)
                if delay:
                    self.budget.host_intervals[parts.hostname] = delay
            except SourceUnavailable as exc:
                if exc.availability != 'not_available':
                    raise SourceUnavailable('Robots access could not be established', 'blocked') from exc
                parser.parse([])
            self.robots[origin] = parser
        if not self.robots[origin].can_fetch(USER_AGENT, url):
            raise SourceUnavailable('Robots disallows URL', 'blocked')
