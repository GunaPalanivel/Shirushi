"""Reproduce the captured nullable-attribute crash on a fixed old commit."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = r'''
import json
from shirushi.web_sources import Page, locale_links
raw = b'<a title href="/contact">Contact</a><link hreflang href="/empty"><script type>skip</script><a hreflang data-language="NB-NO" href="/nb-no/">Norsk</a>'
try:
    page = Page(raw)
    result = {'status': 'PASS', 'locales': locale_links(raw, 'https://example.com/'), 'scripts': page.scripts}
except Exception as exc:
    result = {'status': 'FAIL', 'error_type': type(exc).__name__, 'reason': str(exc)}
print(json.dumps(result))
'''

def run(root):
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    process = subprocess.run([sys.executable, '-X', 'dev', '-W', 'error', '-c', PROGRAM],
        cwd=root, env=environment, capture_output=True, text=True, check=True, timeout=30)
    return json.loads(process.stdout)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', type=Path, required=True)
    args = parser.parse_args()
    control, repaired = run(args.baseline_root.resolve()), run(ROOT)
    if control.get('error_type') != 'AttributeError' or 'lower' not in control.get('reason', ''):
        raise ValueError('Fixed pre-repair control did not reproduce the captured error')
    if repaired != {'status': 'PASS', 'locales': ['https://example.com/nb-no/'], 'scripts': []}:
        raise ValueError('Repaired parser changed expected observed links or script handling')
    print(json.dumps({'status': 'PASS', 'control': control, 'repaired': repaired,
        'scope': 'Same nullable HTML input on fixed old parser and current parser; no network or provider calls'}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
