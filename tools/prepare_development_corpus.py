"""Deterministic proportional development corpus; never selects official inputs."""
import argparse
import gzip
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shirushi.contracts import load, loads  # noqa: E402
from shirushi.registry import find_rows  # noqa: E402
from shirushi.run import write_new  # noqa: E402
from shirushi.snapshots import digest  # noqa: E402


def registered_host(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value if '://' in value else 'https://' + value)
        host = (parsed.hostname or '').lower().rstrip('.').removeprefix('www.')
        return host or None
    except ValueError:
        return None


def employee_band(value):
    if type(value) is not int or value == 0:
        return '0_unknown'
    return '1_9' if value < 10 else '10_49' if value < 50 else '50_plus'


def sample(rows, total=500, seed=20261007):
    strata = defaultdict(list)
    counts = Counter()
    for row in rows:
        host = registered_host(row.get('website'))
        key = (row.get('legal_form') or 'unknown', employee_band(row.get('employees')),
               'present' if row.get('website') else 'absent',
               str(row.get('industry_code') or 'unknown')[:2], str(row.get('municipality_number') or 'unknown'))
        identity = row['organisation_number']
        rank = digest(f'{seed}:{identity}'.encode())
        strata[key].append((rank, identity, host))
        counts[key] += 1
    population = sum(counts.values())
    if population < total:
        raise ValueError('Not enough corpus records')
    quotas = {key: total * count // population for key, count in counts.items()}
    remainders = sorted(counts, key=lambda k: (-(total * counts[k] % population), k))
    for key in remainders[:total - sum(quotas.values())]:
        quotas[key] += 1
    for values in strata.values():
        values.sort(reverse=True)
    selected, used_hosts, exclusions = [], set(), []

    def take(key):
        while strata[key]:
            rank, identity, host = strata[key].pop()
            if host and host in used_hosts:
                exclusions.append({'organisation_number': identity, 'host': host, 'reason': 'already_selected_host_group'})
                continue
            if host:
                used_hosts.add(host)
            selected.append({'organisation_number': identity, 'registered_host_group': host,
                             'stratum': list(key), 'rank': rank})
            return True
        return False

    for key in sorted(quotas):
        for _ in range(quotas[key]):
            take(key)
    # Host conflicts consume no slot. Replace proportionally, recording deviations.
    while len(selected) < total:
        observed = Counter(tuple(row['stratum']) for row in selected)
        choices = sorted((k for k in strata if strata[k]),
                         key=lambda k: (-(total * counts[k] / population - observed[k]), k))
        if not choices or not any(take(k) for k in choices):
            raise ValueError('Insufficient independent registered host groups')
    selected.sort(key=lambda row: row['rank'])
    observed = Counter(tuple(row['stratum']) for row in selected)
    return selected, {'seed': seed, 'algorithm': 'five-way-largest-remainder-host-representative-v1',
                      'population': population, 'selected': total, 'known_corporate_groups_available': False,
                      'host_group_policy': 'One representative per known registered host; ownership is not inferred.',
                      'group_exclusions': exclusions,
                      'strata': [{'key': list(k), 'population': counts[k], 'quota': quotas[k], 'selected': observed[k]}
                                 for k in sorted(counts)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    raw, receipt = args.registry.read_bytes(), load(args.receipt)
    compressed = args.registry.name.endswith('.gz')
    find_rows(raw, receipt, [], compressed)
    stream = gzip.GzipFile(fileobj=io.BytesIO(raw)) if compressed else io.BytesIO(raw)
    with stream:
        selected, manifest = sample(loads(line) for line in stream if line.strip())
    manifest['registry_sha256'] = receipt['sha256']
    manifest['registry_receipt_sha256'] = digest(args.receipt.read_bytes())
    manifest['splits'] = {'development': 100, 'validation': 100, 'final': 300, 'pilot_is_first_development': 20}
    for name, start, end in [('development', 0, 100), ('validation', 100, 200), ('final', 200, 500), ('pilot', 0, 20)]:
        rows = [{'organisation_number': r['organisation_number']} for r in selected[start:end]]
        path = args.output_dir / (name + '.jsonl')
        write_new(path, rows, jsonl=True)
        manifest[name + '_sha256'] = digest(path.read_bytes())
    manifest['selected_records'] = selected
    write_new(args.output_dir / 'corpus-manifest.json', manifest)
    print(json.dumps({'status': 'prepared', 'pilot': 20, 'development': 100, 'validation': 100, 'final': 300}))


if __name__ == '__main__':
    main()
