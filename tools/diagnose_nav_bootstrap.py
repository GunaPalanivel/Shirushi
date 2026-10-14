"""Compare NAV bootstrap at 10/30 seconds without retaining tokens or bodies."""
import argparse
import email.utils
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shirushi.contracts import ROOT, load, loads
from shirushi.fetch import Budget, Fetcher, SourceUnavailable
from shirushi.nav_jobs import HOST


def probe(timeout):
    config = load(ROOT / 'configs/local-live.json')
    config.update(request_timeout_seconds=timeout, max_retries=0, request_budget=2,
                  wall_time_seconds=90, min_host_interval_seconds=.25)
    budget = Budget(config, time.monotonic() + 90)
    fetcher = Fetcher(budget)
    started = time.monotonic()
    stage = 'public_token'
    result = {'request_timeout_seconds': timeout}
    try:
        raw, _ = fetcher.get('https://' + HOST + '/api/publicToken', {HOST})
        tokens = re.findall(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', raw.decode('utf-8'))
        if len(tokens) != 1:
            raise SourceUnavailable('Invalid public token response')
        result['public_token'] = 'available'
        stage = 'feed_page'
        since = email.utils.format_datetime(datetime.now(timezone.utc) - timedelta(days=7), usegmt=True)
        raw, _ = fetcher.get('https://' + HOST + '/api/v1/feed', {HOST},
            request_headers={'Authorization': 'Bearer ' + tokens[0], 'If-Modified-Since': since})
        page = loads(raw)
        if not isinstance(page, dict) or not isinstance(page.get('items'), list):
            raise SourceUnavailable('Invalid feed page')
        result.update(status='available', items=len(page['items']))
    except (SourceUnavailable, ValueError) as exc:
        # Report the failure class only. Upstream bodies and tokens stay private.
        reason = str(exc)
        result.update(status='unavailable', failed_stage=stage,
                      failure='timeout' if 'TimeoutError' in reason else type(exc).__name__)
    result.update(runtime_ms=round((time.monotonic() - started) * 1000), operations=budget.emit())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [probe(timeout) for timeout in (10, 30)]
    report = {'probes': results, 'scope': 'Source availability diagnostic; no coverage or score assertion'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
