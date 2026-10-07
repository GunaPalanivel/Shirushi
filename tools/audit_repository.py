"""Audit local repository and evidence provenance; never contacts the network or writes Git."""
import gzip
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import tarfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_contracts import load, validate_config  # noqa: E402


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def command(*args):
    result = subprocess.run(args, cwd=ROOT, text=True, encoding='utf-8', capture_output=True)
    return {'exit_code': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}


def main():
    receipt_dir = ROOT / '.idea/buildDocs/repository-audit'
    receipt_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    runtime = {'python': platform.python_version(), 'executable': sys.executable,
               'platform': platform.platform(), 'isolated': sys.prefix != sys.base_prefix,
               'installed_distributions': sorted(d.metadata['Name'] for d in importlib.metadata.distributions())}
    baseline = load(ROOT / 'configs/runtime-baseline.json')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    if runtime['python'] != baseline['python'] or not runtime['isolated']:
        errors.append('Use the isolated pinned Python runtime')
    if baseline['third_party_dependencies'] or project['project']['dependencies'] or runtime['installed_distributions']:
        errors.append('repository bootstrap stdlib-only dependency baseline differs')
    git = {'branch': command('git', 'branch', '--show-current'),
           'origin': command('git', 'config', '--get', 'remote.origin.url'),
           'head': command('git', 'rev-parse', 'HEAD'),
           'ignore': command('git', 'check-ignore', '-v', '.idea/rawData/researchDirection.md'),
           'tracked_idea': command('git', 'ls-files', '--', '.idea'),
           'status': command('git', 'status', '--short')}
    if git['branch']['stdout'] != 'main' or git['origin']['stdout'] != 'https://github.com/GunaPalanivel/Shirushi.git':
        errors.append('Repository baseline branch/origin differs')
    if git['ignore']['exit_code'] != 0 or git['tracked_idea']['stdout']:
        errors.append('.idea is not ignored or is tracked')
    raw = ROOT / '.idea/rawData'
    reviewed = []
    for path in [raw / 'researchDirection.md'] + sorted((ROOT / '.idea/buildDocs').glob('*.md')):
        reviewed.append({'path': path.relative_to(ROOT).as_posix(), 'lines': len(path.read_text(encoding='utf-8-sig').splitlines()), 'sha256': sha(path)})
    universe = raw / 'builderPage/zips/signalpost-company-universe-2025.jsonl.gz'
    digest, identities, rows = hashlib.sha256(), set(), 0
    with gzip.open(universe, 'rb') as stream:
        for line in stream:
            digest.update(line)
            if not line.strip():
                continue
            record = json.loads(line)
            identity = str(record.get('organisation_number', ''))
            if re.fullmatch(r'[0-9]{9}', identity) is None or identity in identities:
                errors.append(f'Invalid or duplicate universe row {rows + 1}')
            identities.add(identity)
            rows += 1
    universe_audit = {'rows': rows, 'unique_ids': len(identities), 'compressed_sha256': sha(universe), 'uncompressed_sha256': digest.hexdigest()}
    if (rows != 411160 or universe_audit['compressed_sha256'] != '1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384'
            or digest.hexdigest() != 'b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838'):
        errors.append('Universe does not match official snapshot identity')
    archive = raw / 'builderPage/zips/signalpost-starter-kit.tar.gz'
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        unsafe = [m.name for m in members if PurePosixPath(m.name).is_absolute() or PureWindowsPath(m.name).drive
                  or '..' in PurePosixPath(m.name.replace('\\', '/')).parts or m.issym() or m.islnk()
                  or not (m.isfile() or m.isdir())]
        licences = [m.name for m in members if m.isfile() and PurePosixPath(m.name).name.lower().startswith(('license', 'licence', 'copying', 'notice'))]
        inventory = {'sha256': sha(archive), 'member_count': len(members), 'unsafe_members': unsafe,
                     'licence_members': licences, 'reuse_status': 'not_established_inspection_only',
                     'extracted': False, 'members': [{'name': m.name, 'size': m.size, 'type': m.type.decode('ascii', errors='replace')} for m in members]}
    if unsafe or inventory['sha256'] != 'd48da9910ea7de07d2bf51ab265539a35fe07002a6c1ca5787df81316dfabbf6':
        errors.append('Unsafe or changed starter archive')
    (receipt_dir / 'archive-audit.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    sources = load(ROOT / '.idea/buildDocs/engineering-standards/evidence/manifest.json')['sources']
    for source in sources:
        path = ROOT / source['path']
        if source['status'] != 'captured' or not path.is_file() or sha(path) != source['sha256']:
            errors.append('Unavailable or changed official source: ' + source['id'])
    policy = load(ROOT / 'configs/source-policy.json')
    configs = {}
    for path in sorted((ROOT / 'configs').glob('local-*.json')):
        config_errors = validate_config(load(path), policy)
        configs[path.name] = {'sha256': sha(path), 'errors': config_errors}
        errors.extend(config_errors)
    rejected_official = validate_config(load(ROOT / 'configs/official-run.template.json'), policy)
    if not rejected_official:
        errors.append('Unconfirmed official template unexpectedly accepted')
    tests = command(sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    if tests['exit_code']:
        errors.append('Boundary test suite failed')
    workflow = (ROOT / '.github/workflows/contract-validation.yml').read_text(encoding='utf-8')
    action_refs = re.findall(r'uses:\s*(\S+)', workflow)
    if len(action_refs) != 2 or any(re.fullmatch(r'actions/(?:checkout|setup-python)@[0-9a-f]{40}', ref) is None for ref in action_refs):
        errors.append('CI actions must use reviewed immutable commit references')
    if 'contents: read' not in workflow or 'persist-credentials: false' not in workflow or 'pull_request_target' in workflow:
        errors.append('CI permission or checkout policy differs')
    link_count = 0
    for path in [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', ROOT / 'SECURITY.md'] + sorted((ROOT / 'docs').glob('*.md')):
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if target.startswith(('https:', 'http:', '#')):
                continue
            link_count += 1
            if not (path.parent / target.split('#')[0].strip('<>')).exists():
                errors.append(f'Broken tracked document link: {path.name}: {target}')
    paths = [ROOT / name for name in ('.gitignore', '.python-version', 'pyproject.toml', 'README.md',
                                      'CONTRIBUTING.md', 'SECURITY.md', '.editorconfig', '.gitattributes')]
    for directory in ('docs', 'configs', 'contracts', 'shirushi', 'tools', 'tests', '.github'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'status': 'PASS' if not errors else 'FAIL', 'scope': 'repository_bootstrap',
              'local_foundation_complete': not errors, 'official_release_ready': False,
              'saved_company_integration_implemented': True, 'live_agent_implemented': False, 'official_score': None,
              'runtime': runtime, 'git': git, 'reviewed_inputs': reviewed, 'universe': universe_audit,
              'archive': {k: v for k, v in inventory.items() if k != 'members'},
              'official_source_receipts': sources, 'local_configs': configs,
              'official_template_expected_rejection': rejected_official,
              'tests': tests, 'local_document_links_checked': link_count,
              'ci_action_references': action_refs, 'hosted_ci_run': False,
              'artifact_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)},
              'errors': errors,
              'limitations': ['Boundary and provenance checks are not source-truth or independent research adjudication.',
                             'No network adapters, official score, frozen release or public submission.',
                             'Current source receipts can drift; recheck before release.']}
    (receipt_dir / 'validation-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'scope': 'repository_bootstrap', 'universe_rows': rows,
                      'archive_members': len(members), 'source_receipts': len(sources),
                      'tests_exit_code': tests['exit_code'], 'errors': errors,
                      'receipt': '.idea/buildDocs/repository-audit/validation-report.json'}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
