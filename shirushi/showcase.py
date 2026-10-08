"""Static, escaped profiles composed only from accepted claims and evidence."""
import json
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from .artifacts import publish_new

CSS = '''body{font:16px system-ui;margin:1rem auto;padding:0 1rem;max-width:70rem;line-height:1.5;color:#162536;background:#fff}
a{color:#1247a0} :focus-visible{outline:3px solid #1247a0;outline-offset:3px} input{font:inherit;padding:.5rem;max-width:95%}
table{width:100%;border-collapse:collapse} td,th{text-align:left;border-bottom:1px solid #ddd;padding:.6rem;vertical-align:top;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:.4rem 0} .compare{display:flex;gap:1rem;flex-wrap:wrap}.compare section{flex:1;min-width:15rem}
@media(max-width:600px){table,tbody,tr,td{display:block}thead{display:none}td{padding:.3rem}tr{margin-bottom:1rem;border-bottom:1px solid #bbb}}'''


def text(value):
    return escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True))


def summary(envelope):
    available = [c for c in envelope['claims'] if c['availability'] == 'available']
    name = next((c['value'] for c in available if c['field'] == 'legal_name'), envelope['organisation_number'])
    description = next((c for c in available if c['field'] in ('business_description', 'product_service')), None)
    if description is None:
        description = next((c for c in available if c['field'] == 'registered_activity'), None)
    lines = [text(name) + ' (' + envelope['organisation_number'] + ').']
    if description:
        label = 'Registered activity: ' if description['field'] == 'registered_activity' else 'Supported description: '
        lines.append(label + text(description['value']) + '.')
    lines.append(str(len(envelope['changes'])) + ' supported value changes in this run.')
    unknown = [o['family'] for o in envelope.get('opportunities', []) if o['status'] != 'covered']
    if unknown:
        lines.append('No verified coverage for: ' + ', '.join(unknown) + '.')
    return ' '.join(lines)


def profile(envelope):
    evidence = {e['id']: e for e in envelope['evidence']}
    rows = []
    for claim in envelope['claims']:
        sources = []
        for ref in claim['evidence_ids']:
            item = evidence[ref]
            if urlsplit(item['source_url']).scheme != 'https':
                raise ValueError('Profile source link must use HTTPS')
            sources.append('<details><summary>Evidence</summary><a rel="noopener noreferrer" href="' +
                           escape(item['source_url'], quote=True) + '">Original source</a><p>Retrieved: ' +
                           text(item['retrieved_at']) + '</p><p>SHA-256: ' + text(item['content_sha256']) +
                           '</p><pre>' + text(item['claim_span'][:2000]) + '</pre></details>')
        rows.append('<tr><th scope="row">' + text(claim['field']) + '</th><td>' + text(claim['value']) +
                    '</td><td>' + text(claim['availability']) + ' ' + text(claim.get('freshness', claim.get('reason', ''))) +
                    '</td><td>' + ''.join(sources) + '</td></tr>')
    return ('<p>' + summary(envelope) + '</p><table><thead><tr><th>Fact</th><th>Value</th><th>Status</th><th>Sources</th></tr></thead>' +
            '<tbody>' + ''.join(rows) + '</tbody></table><h2>Changes</h2><pre>' + text(envelope['changes']) +
            '</pre><h2>Prior supported values</h2><pre>' + text(envelope.get('history', [])) + '</pre>')


def document(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
            '<title>' + escape(title) + '</title><style>' + CSS + '</style><main>' + body + '</main></html>').encode('utf-8')


def render(envelopes, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    root = directory / 'signalpost'
    root.mkdir()
    rows = []
    for envelope in envelopes:
        subject = envelope['organisation_number']
        publish_new(root / (subject + '.html'), document(subject, '<a href="index.html">All companies</a><h1>' + subject + '</h1>' + profile(envelope)))
        rows.append('<tr data-company><td><input type="checkbox" aria-label="Compare ' + subject + '"></td><td><a href="' + subject +
                    '.html">' + subject + '</a></td><td>' + summary(envelope) + '</td></tr>')
    script = '''<script>
const rows=[...document.querySelectorAll('[data-company]')];
document.querySelector('#search').addEventListener('input',e=>rows.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())));
document.querySelector('#compare').addEventListener('click',()=>{
const selected=rows.filter(r=>r.querySelector('input').checked);
const output=document.querySelector('#comparison');output.replaceChildren();
selected.forEach(r=>{const section=document.createElement('section');const title=document.createElement('h2');title.append(r.cells[1].querySelector('a').cloneNode(true));const text=document.createElement('p');text.textContent=r.cells[2].textContent;section.append(title,text);output.append(section)});
document.querySelector('#count').textContent=selected.length+' companies selected';});
</script>'''
    body = ('<h1>Signalpost</h1><p>Local evidence-backed profiles. Official score unmeasured.</p>' +
            '<label for="search">Search company number, name or activity</label><input id="search" type="search">' +
            '<button id="compare">Compare selected companies</button><p id="count" role="status"></p><div id="comparison" class="compare"></div>' +
            '<table><thead><tr><th>Select</th><th>Company</th><th>Supported summary</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>' + script)
    publish_new(root / 'index.html', document('Signalpost', body))
