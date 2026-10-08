"""Static, escaped profiles composed only from accepted claims and evidence."""
import json
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from .artifacts import publish_new
from .snapshots import digest

FAMILY_LABELS = {'business_products': 'business and products', 'people': 'people',
    'operating_locations': 'operating locations', 'financials_history': 'financial history',
    'website_owned_profiles': 'verified websites', 'jobs_dated_activity': 'jobs and dated activity'}
FIELD_LABELS = {'legal_name': 'Legal name', 'legal_form': 'Legal form', 'registered_activity': 'Registered activity',
    'registered_employees': 'Registered employees', 'verified_website': 'Verified website', 'official_website': 'Verified website',
    'business_description': 'Business description', 'product_service': 'Products and services',
    'job_posting': 'Job posting', 'public_activity': 'Dated activity', 'operating_location': 'Operating location',
    'annual_revenue': 'Annual revenue', 'latest_submitted_accounts_year': 'Latest accounts filing year'}

CSS = '''body{font:16px system-ui;margin:1rem auto;padding:0 1rem;max-width:70rem;line-height:1.5;color:#162536;background:#fff}
a{color:#1247a0} :focus-visible{outline:3px solid #1247a0;outline-offset:3px} input{font:inherit;padding:.5rem;max-width:95%}
table{width:100%;border-collapse:collapse} td,th{text-align:left;border-bottom:1px solid #ddd;padding:.6rem;vertical-align:top;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:.4rem 0} .compare{display:flex;gap:1rem;flex-wrap:wrap}.compare section{flex:1;min-width:0;width:100%}
button{font:inherit;padding:.6rem;margin:.4rem 0} .context{display:block;font-size:.9rem;color:#42556b} .summary{line-height:1.7}
[hidden]{display:none!important}
@media(max-width:600px){table,tbody,tr,td,th{display:block}thead{display:none}td,th{padding:.3rem}tr{margin-bottom:1rem;border-bottom:1px solid #bbb}.compare{display:block}}'''


def text(value):
    return escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True))


def label(field):
    if field.startswith('coverage:'):
        return 'Coverage: ' + FAMILY_LABELS.get(field.split(':', 1)[1], field)
    if field.startswith('registered_role:'):
        return 'Registered role'
    return FIELD_LABELS.get(field, field.replace('_', ' ').capitalize())


def anchor(ref):
    return 'evidence-' + digest(ref.encode())[:24]


def claim_link(claim, prefix=''):
    return prefix + '#' + anchor(claim['evidence_ids'][0])


def display_value(claim):
    value = claim['value']
    if claim['availability'] != 'available':
        return 'Unknown' if claim['availability'] != 'not_applicable' else 'Not applicable'
    if isinstance(value, dict) and 'amount' in value:
        return str(value['amount']) + ' ' + str(value.get('currency', '')) + ' (raw source units)'
    if isinstance(value, dict) and 'person_name' in value:
        return str(value['person_name']) + ' / ' + str(value.get('role_code', ''))
    if isinstance(value, dict) and 'title' in value:
        return str(value['title']) + ' / posted ' + str(value.get('date_posted', 'unknown'))
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def context(claim):
    values = []
    if claim.get('period'):
        period = claim['period']
        values.append('Period: ' + (period['fraDato'] + ' to ' + period['tilDato'] if isinstance(period, dict) and {'fraDato', 'tilDato'} <= period.keys() else str(period)))
    if claim.get('scope'):
        values.append('Scope: ' + claim['scope'].replace('_', ' '))
    if claim.get('freshness'):
        values.append(claim['freshness'].replace('_', ' '))
    if claim.get('current_attempt_reason'):
        values.append('Latest check: ' + claim['current_attempt_reason'])
    return '; '.join(values)


def summary(envelope, prefix=''):
    available = [c for c in envelope['claims'] if c['availability'] == 'available']
    name = next((c for c in available if c['field'] == 'legal_name'), None)
    description = next((c for c in available if c['field'] in ('business_description', 'product_service')), None)
    if description is None:
        description = next((c for c in available if c['field'] == 'registered_activity'), None)
    def supported(claim):
        return '<a href="' + escape(claim_link(claim, prefix), quote=True) + '">' + text(display_value(claim)) + '</a>'
    lines = [(supported(name) if name else envelope['organisation_number']) + ' (' + envelope['organisation_number'] + ').']
    if description:
        label = 'Registered activity: ' if description['field'] == 'registered_activity' else 'Supported description: '
        lines.append(label + supported(description) + '.')
    employees = next((c for c in available if c['field'] == 'registered_employees'), None)
    if employees:
        lines.append('Registered employees: ' + supported(employees) + '.')
    revenue = [c for c in available if c['field'] == 'annual_revenue' and c.get('scope') == 'entity_accounts']
    if revenue:
        latest = max(revenue, key=lambda c: (c['period']['tilDato'], c['period']['fraDato']))
        lines.append('Latest supported entity revenue: ' + supported(latest) + ' (' + text(context(latest)) + ').')
    changed = sum(c.get('kind') == 'value_changed' for c in envelope['changes'])
    lines.append(str(changed) + ' supported value changes in this run.')
    unknown = [o['family'] for o in envelope.get('opportunities', []) if o['status'] != 'covered']
    if unknown:
        lines.append('No verified coverage for: ' + ', '.join(FAMILY_LABELS.get(f, f) for f in unknown) + '.')
    return ' '.join(lines)


def profile(envelope):
    evidence = {e['id']: e for e in envelope['evidence']}
    displayed = set()

    def sources_for(claim):
        sources = []
        for ref in claim['evidence_ids']:
            item = evidence[ref]
            if urlsplit(item['source_url']).scheme != 'https':
                raise ValueError('Profile source link must use HTTPS')
            if ref in displayed:
                sources.append('<a href="#' + anchor(ref) + '">Evidence</a>')
                continue
            displayed.add(ref)
            sources.append('<details id="' + anchor(ref) + '"><summary>Evidence</summary><a rel="noopener noreferrer" href="' +
                           escape(item['source_url'], quote=True) + '">Original source</a><p>Retrieved: ' +
                           text(item['retrieved_at']) + '</p><p>SHA-256: ' + text(item['content_sha256']) +
                           '</p><pre>' + text(item['claim_span'][:2000]) + '</pre></details>')
        return ''.join(sources)

    def fact_row(claim):
        status = claim['availability'].replace('_', ' ')
        reason = claim.get('reason', '')
        return ('<tr><th scope="row">' + text(label(claim['field'])) + '</th><td>' + text(display_value(claim)) +
                '<span class="context">' + text(context(claim)) + '</span></td><td>' + text(status) + ' ' +
                text(reason) + '</td><td>' + sources_for(claim) + '</td></tr>')

    rows = ''.join(fact_row(claim) for claim in envelope['claims'])
    # Retain the private audit history without republishing withdrawn vacancies.
    changes = [c for c in envelope['changes'] if c['field'] != 'job_posting']
    history = [c for c in envelope.get('history', [])
               if c['field'] != 'job_posting' and c.get('scope') != 'nav_verified_employer']
    change_rows = []
    for change in changes:
        cells = []
        for key in ('old_value', 'new_value'):
            value = change[key]
            rendered = display_value({'value': value, 'availability': 'available' if value is not None else 'not_available'})
            refs = change['old_evidence_ids' if key == 'old_value' else 'new_evidence_ids']
            link = '<a href="#' + anchor(refs[0]) + '">' + text(rendered) + '</a>' if refs else text(rendered)
            cells.append('<td>' + link + '</td>')
        change_rows.append('<tr><th scope="row">' + text(label(change['field'])) + '</th>' + ''.join(cells) +
                           '<td>' + text(change['observed_at']) + '</td></tr>')
    change_panel = ('<table><thead><tr><th>Fact</th><th>Previous</th><th>Current</th><th>Observed</th></tr></thead><tbody>' +
                    ''.join(change_rows) + '</tbody></table>') if changes else '<p>No supported value changes in this run.</p>'
    prior_panel = ('<table><tbody>' + ''.join(fact_row(c) for c in history) + '</tbody></table>') if history else '<p>No prior supported values.</p>'
    return ('<p class="summary">' + summary(envelope) + '</p><table><thead><tr><th>Fact</th><th>Value</th><th>Status</th><th>Sources</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table><h2>Changes</h2>' + change_panel + '<h2>Prior supported values</h2>' + prior_panel)


def document(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
            '<title>' + escape(title) + '</title><style>' + CSS + '</style><main>' + body + '</main></html>').encode('utf-8')


def render(envelopes, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    root = directory / 'signalpost'
    root.mkdir()
    rows = []
    comparisons = {}
    for envelope in envelopes:
        subject = envelope['organisation_number']
        name = next((c['value'] for c in envelope['claims'] if c['field'] == 'legal_name' and c['availability'] == 'available'), subject)
        publish_new(root / (subject + '.html'), document(str(name), '<a href="index.html">All companies</a><h1>' + text(name) +
            '</h1><p>Organisation number: ' + subject + '</p>' + profile(envelope)))
        rows.append('<tr data-company="' + subject + '"><td><input type="checkbox" aria-label="Compare ' + subject + '"></td><td><a href="' + subject +
                    '.html">' + text(name) + '<br>' + subject + '</a></td><td>' + summary(envelope, subject + '.html') + '</td></tr>')
        comparisons[subject] = {'name': name, 'facts': [{'label': label(c['field']), 'value': display_value(c),
            'context': context(c), 'status': c['availability'], 'reason': c.get('reason', ''),
            'href': claim_link(c, subject + '.html') if c['availability'] == 'available' else subject + '.html'}
            for c in envelope['claims']]}
    script = '''<script>
const rows=[...document.querySelectorAll('[data-company]')];
const companies=JSON.parse(document.querySelector('#company-data').textContent);
document.querySelector('#search').addEventListener('input',e=>{rows.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase()));document.querySelector('#results').textContent=rows.filter(r=>!r.hidden).length+' companies shown'});
document.querySelector('#compare').addEventListener('click',()=>{
const selected=rows.filter(r=>r.querySelector('input').checked);
if(selected.length>3){document.querySelector('#count').textContent='Choose up to three companies to compare';return;}
const output=document.querySelector('#comparison');output.replaceChildren();
selected.forEach(r=>{const data=companies[r.dataset.company];const section=document.createElement('section');const title=document.createElement('h2');title.textContent=data.name;const table=document.createElement('table');const body=document.createElement('tbody');data.facts.forEach(f=>{const row=document.createElement('tr');const heading=document.createElement('th');heading.scope='row';heading.textContent=f.label;const cell=document.createElement('td');const link=document.createElement('a');link.href=f.href;link.textContent=f.value;const details=document.createElement('span');details.className='context';details.textContent=f.status+'; '+f.context+'; '+f.reason;cell.append(link,details);row.append(heading,cell);body.append(row)});table.append(body);section.append(title,table);output.append(section)});
document.querySelector('#count').textContent=selected.length+' companies selected';});
</script>'''
    data = json.dumps(comparisons, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    body = ('<h1>Signalpost</h1><p>Research companies, compare supported facts and inspect their original sources.</p>' +
            '<label for="search">Search company number, name or activity</label><input id="search" type="search">' +
            '<p id="results" role="status">' + str(len(rows)) + ' companies shown</p>' +
            '<button id="compare">Compare selected companies</button><p id="count" role="status"></p><div id="comparison" class="compare"></div>' +
            '<table><thead><tr><th>Select</th><th>Company</th><th>Supported summary</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>' +
            '<script id="company-data" type="application/json">' + data + '</script>' + script)
    publish_new(root / 'index.html', document('Signalpost', body))
