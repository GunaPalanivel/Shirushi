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
#comparison,#comparison p,#comparison a{overflow-wrap:anywhere}
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


def reason_text(reason):
    return {'frozen_snapshot': '', 'absent_in_frozen_row': 'The source does not supply this fact.',
            'unobserved_in_current_sources': 'The latest sources do not confirm the previous value.',
            'older_source_cannot_replace_newer_verified_value': 'The latest source is older than the retained evidence.'
            }.get(reason, reason.replace('_', ' '))


AVAILABILITY_LABELS = {
    'available': 'Available',
    'not_available': 'Not found in checked sources',
    'blocked': 'Blocked',
    'not_applicable': 'Not applicable',
    'ambiguous': 'Ambiguous',
    'failed': 'Not checked',
}


def availability_text(state):
    return AVAILABILITY_LABELS[state]


def plain(value):
    if value is None:
        return 'none'
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict) and 'statement' in value:
        return str(value['statement'])
    if isinstance(value, dict) and 'platform' in value:
        return str(value.get('platform', '')) + ' ' + str(value.get('url', ''))
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def summary_parts(envelope):
    """One traceable sentence per supported fact group. Indexes point at claims and changes."""
    claims = envelope.get('claims') or []
    changes = envelope.get('changes') or []
    parts = []

    def add(section, claim_indexes, sentence, change_indexes=()):
        parts.append({'section': section, 'text': sentence, 'claims': list(claim_indexes),
                      'changes': list(change_indexes)})

    what = []
    what_indexes = []
    for field, phrase in (
            ('legal_name', '{}'),
            ('legal_form', 'is registered as {}'),
            ('registered_municipality', 'in {}'),
            ('industry_label', 'Industry {}.'),
            ('registered_employees', 'Registered employees: {}.'),
    ):
        found = next(((i, c) for i, c in enumerate(claims)
                      if c.get('field') == field and c.get('availability') == 'available'), None)
        if found is None:
            continue
        index, claim = found
        what_indexes.append(index)
        what.append(phrase.format(plain(claim.get('value'))))
    if what_indexes:
        lead = ' '.join(what[:3]).strip()
        rest = ' '.join(what[3:])
        add('what', what_indexes, (lead + ' ' + rest).strip())

    for field, phrase in (
            ('verified_website', 'Verified website: {}.'),
            ('official_website', 'Verified website: {}.'),
            ('business_description', 'Supported description: {}.'),
            ('product_service', 'Supported description: {}.'),
            ('social_profile', 'Social profile: {}.'),
            ('public_activity', 'Dated activity: {}.'),
    ):
        found = next(((i, c) for i, c in enumerate(claims)
                      if c.get('field') == field and c.get('availability') == 'available'), None)
        if found is None:
            continue
        index, claim = found
        value = claim.get('value')
        if field == 'public_activity' and isinstance(value, dict):
            sentence = 'Dated activity: %s Published %s.' % (value.get('statement', ''), value.get('published_at', ''))
        else:
            sentence = phrase.format(plain(value)).rstrip('.') + '.'
        add('found', [index], sentence)

    for index, claim in enumerate(claims):
        if claim.get('availability') == 'available':
            continue
        add('unknown', [index], '%s: %s. %s' % (label(claim.get('field', '')),
                                                availability_text(claim.get('availability')),
                                                claim.get('reason') or ''))

    shown = [(index, change) for index, change in enumerate(changes) if change.get('field') != 'job_posting']
    emitted = False
    for index, change in shown:
        cited = [i for i, claim in enumerate(claims) if claim.get('field') == change.get('field')][:1]
        if not cited:
            continue
        when = str(change.get('observed_at') or '')[:10]
        add('changed', cited, '%s changed from %s to %s on %s.' % (
            label(change.get('field', '')), plain(change.get('old_value')), plain(change.get('new_value')), when),
            [index])
        emitted = True
    if not emitted:
        cite = [0] if claims else []
        add('changed', cite, 'No changed values in this run.')
    return parts


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
        values.append('Latest check: ' + reason_text(claim['current_attempt_reason']))
    return '; '.join(values)


def summary(envelope, prefix=''):
    available = [c for c in envelope['claims'] if c['availability'] == 'available']
    name = next((c for c in available if c['field'] == 'legal_name'), None)
    description = next((c for c in available if c['field'] in ('business_description', 'product_service')), None)
    if description is None:
        description = next((c for c in available if c['field'] == 'registered_activity'), None)
    def supported(claim):
        return '<a href="' + escape(claim_link(claim, prefix), quote=True) + '">' + text(display_value(claim)) + '</a>'
    when = str((envelope.get('run') or {}).get('completed_at') or '')[:10]
    parts = when.split('-')
    dated = len(parts) == 3 and [len(part) for part in parts] == [4, 2, 2] and all(part.isdigit() for part in parts)
    lead = (supported(name) if name else envelope['organisation_number']) + ' (' + envelope['organisation_number'] + ').'
    lines = [('As of ' + when + ': ' + lead) if dated else lead]
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
        ordered = sorted(revenue, key=lambda c: (c['period']['tilDato'], c['period']['fraDato']))
        if len(ordered) >= 2:
            prior, current = ordered[-2], ordered[-1]
            prior_amount, current_amount = prior.get('value'), current.get('value')
            if (isinstance(prior_amount, dict) and isinstance(current_amount, dict)
                    and prior_amount.get('currency') == current_amount.get('currency')
                    and isinstance(prior_amount.get('amount'), (int, float))
                    and isinstance(current_amount.get('amount'), (int, float))
                    and prior is not current):
                lines.append('Supported entity revenue moved from ' + supported(prior) + ' to ' + supported(current) + '.')
    changed = sum(c.get('kind') == 'value_changed' for c in envelope['changes'])
    lines.append(str(changed) + ' supported value changes in this run.')
    unknown = [o['family'] for o in envelope.get('opportunities', []) if o['status'] != 'covered']
    if unknown:
        lines.append('No verified coverage for: ' + ', '.join(FAMILY_LABELS.get(f, f) for f in unknown) + '.')
    return ' '.join(lines)


def profile(envelope):
    evidence = {e['id']: e for e in envelope['evidence']}
    for item in evidence.values():
        if urlsplit(item['source_url']).scheme != 'https':
            raise ValueError('Profile source link must use HTTPS')
    displayed = set()

    def sources_for(claim):
        sources = []
        for ref in claim['evidence_ids']:
            item = evidence[ref]
            host = urlsplit(item['source_url']).hostname or ''
            line = ('<p class="source-line"><a rel="noopener noreferrer" href="' + escape(item['source_url'], quote=True) +
                    '">' + text(host) + '</a> Retrieved ' + text(item['retrieved_at'][:10]) +
                    ' <a href="#' + anchor(ref) + '">Evidence</a></p>')
            if ref not in displayed:
                displayed.add(ref)
                line += ('<p id="' + anchor(ref) + '">SHA-256: ' + text(item['content_sha256']) + '</p><pre>' +
                         text(item['claim_span'][:2000]) + '</pre>')
            sources.append(line)
        return ''.join(sources)

    def fact_row(claim, index=None):
        reason = reason_text(claim.get('reason', ''))
        identity = '' if index is None else ' id="fact-%d" class="state-%s"' % (index, claim['availability'].replace('_', '-'))
        return ('<tr' + identity + '><th scope="row">' + text(label(claim['field'])) + '</th><td>' + text(display_value(claim)) +
                '<span class="context">' + text(context(claim)) + '</span></td><td>' + text(availability_text(claim['availability'])) +
                ' ' + text(reason) + '</td><td>' + sources_for(claim) + '</td></tr>')

    rows = ''.join(fact_row(claim, index) for index, claim in enumerate(envelope['claims']))
    sentences = ''.join(
        '<li class="sentence" data-section="%s" data-claims="%s">%s</li>' % (
            part['section'], ','.join(str(i) for i in part['claims']), text(part['text']))
        for part in summary_parts(envelope))
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
    return ('<p class="summary">' + summary(envelope) + '</p><ul class="sentences">' + sentences + '</ul>' +
            '<table><thead><tr><th>Fact</th><th>Value</th><th>Status</th><th>Sources</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table><h2>Changes</h2>' + change_panel + '<h2>Prior supported values</h2>' + prior_panel)


def document(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
            '<title>' + escape(title) + '</title><style>' + CSS + '</style><main>' + body + '</main></html>').encode('utf-8')


def area_flags(envelope):
    fields = {c['field'] for c in envelope['claims'] if c.get('availability') == 'available'}
    return {
        'website': bool(fields & {'verified_website', 'official_website'}),
        'description': bool(fields & {'business_description', 'product_service', 'registered_activity'}),
        'profiles': 'social_profile' in fields,
        'activity': bool(fields & {'public_activity', 'job_posting'}),
        'financials': 'annual_revenue' in fields or any(c['field'].startswith('annual_') for c in envelope['claims']
                                                        if c.get('availability') == 'available'),
        'changed': any(c.get('field') != 'job_posting' for c in envelope.get('changes') or []),
    }


def search_text(envelope):
    bits = [str(envelope['organisation_number'])]
    for field in ('legal_name', 'registered_municipality', 'industry_label', 'industry_code', 'registered_activity'):
        for claim in envelope['claims']:
            if claim.get('field') == field and claim.get('availability') == 'available' and isinstance(claim.get('value'), str):
                bits.append(claim['value'])
    return ' '.join(bits).lower()


def shown_value(claim):
    shown = display_value(claim)
    return shown if isinstance(shown, str) else json.dumps(shown, ensure_ascii=False, sort_keys=True)


def compare_section(envelope):
    """One comparison column. A supported value is a link to its source quote on this page."""
    evidence = {item['id']: item for item in envelope['evidence']}
    name = next((c['value'] for c in envelope['claims']
                 if c['field'] == 'legal_name' and c['availability'] == 'available'), envelope['organisation_number'])
    parts = ['<section><h2>' + text(name) + '</h2>']
    seen = set()
    for claim in envelope['claims']:
        parts.append('<p>' + text(label(claim['field'])) + ': ')
        refs = claim.get('evidence_ids') or []
        item = evidence.get(refs[0]) if refs else None
        shown = shown_value(claim)
        if item and item.get('content_sha256') and item.get('retrieved_at'):
            target = anchor(refs[0])
            parts.append('<a href="#' + target + '">' + text(shown) + '</a>')
            if target not in seen:
                seen.add(target)
                parts.append('<details id="' + target + '"><summary>Evidence</summary><p>SHA-256: ' +
                             text(item['content_sha256']) + '</p><p>Retrieved: ' + text(item['retrieved_at']) + '</p></details>')
        else:
            parts.append(text(shown))
        parts.append('</p>')
    parts.append('</section>')
    return ''.join(parts)


def render(envelopes, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    root = directory / 'signalpost'
    root.mkdir()
    cards = []
    for envelope in envelopes:
        subject = envelope['organisation_number']
        name = next((c['value'] for c in envelope['claims'] if c['field'] == 'legal_name' and c['availability'] == 'available'), subject)
        publish_new(root / (subject + '.html'), document(str(name), '<a href="index.html">All companies</a><h1>' + text(name) +
            '</h1><p>Organisation number: ' + subject + '</p>' + profile(envelope)))
        flags = area_flags(envelope)
        cards.append('<li class="company" data-company="%s" data-areas="%d" data-search="%s" data-website="%d" data-description="%d" data-profiles="%d" data-activity="%d" data-financials="%d" data-changed="%d"><input type="checkbox" aria-label="Compare %s"><a href="%s.html">%s</a><p>%s</p></li>' % (
            escape(subject, quote=True), sum(flags.values()), escape(search_text(envelope), quote=True),
            int(flags['website']), int(flags['description']), int(flags['profiles']), int(flags['activity']),
            int(flags['financials']), int(flags['changed']), escape(subject, quote=True),
            escape(subject, quote=True), text(name), text(subject)))
    filters = ''.join(
        '<button type="button" data-filter="%s" aria-pressed="false">%s</button>' % pair
        for pair in (('website', 'Website'), ('description', 'Description'), ('profiles', 'Profiles'),
                     ('activity', 'Activity'), ('financials', 'Financials'), ('changed', 'Changed')))
    packed = json.dumps({envelope['organisation_number']: compare_section(envelope) for envelope in envelopes},
                        ensure_ascii=False).replace('<', '\\u003c')
    body = ('<h1>Signalpost</h1><p>Research companies, compare supported facts and inspect their original sources.</p>' +
            '<label for="search">Search company number, name or activity</label><input id="search" type="search">' +
            '<p id="results" role="status">' + str(len(cards)) + ' companies shown</p>' + filters +
            '<label for="sort">Sort</label><select id="sort"><option value="name">Name</option><option value="areas">Most data</option></select>' +
            '<button type="button" id="compare-go">Compare selected companies</button>' +
            '<div id="comparison" class="compare"></div><div id="compare-panel"></div><ul id="companies">' +
            ''.join(cards) + '</ul><script type="application/json" id="compare-data">' + packed + '</script>' + INDEX_SCRIPT)
    publish_new(root / 'index.html', document('Signalpost', body))


INDEX_SCRIPT = '''<script>
(function () {
  var list = document.querySelector('#companies');
  var cards = [].slice.call(list.children);
  var search = document.querySelector('#search');
  var sort = document.querySelector('#sort');
  var results = document.querySelector('#results');
  var panel = document.querySelector('#compare-panel');
  var filters = [].slice.call(document.querySelectorAll('[data-filter]'));
  var areas = ['website', 'description', 'profiles', 'activity', 'financials', 'changed'];
  function fold(value) {
    return value.toLowerCase().replace(/æ/g, 'ae').replace(/ø/g, 'o').replace(/å/g, 'a');
  }
  function apply() {
    var query = fold(search.value);
    var required = filters.filter(function (button) { return button.getAttribute('aria-pressed') === 'true'; })
      .map(function (button) { return button.getAttribute('data-filter'); });
    var shown = cards.filter(function (card) {
      if (query && fold(card.getAttribute('data-search') || '').indexOf(query) < 0) return false;
      return required.every(function (key) { return card.getAttribute('data-' + key) === '1'; });
    });
    shown.sort(function (left, right) {
      if (sort.value === 'areas') return Number(right.getAttribute('data-areas')) - Number(left.getAttribute('data-areas'));
      return (left.textContent || '').localeCompare(right.textContent || '');
    });
    cards.forEach(function (card) { card.hidden = shown.indexOf(card) < 0; });
    shown.forEach(function (card) { list.appendChild(card); });
    results.textContent = shown.length + ' companies shown';
  }
  search.addEventListener('input', apply);
  sort.addEventListener('change', apply);
  filters.forEach(function (button) {
    button.addEventListener('click', function () {
      button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      apply();
    });
  });
  list.addEventListener('change', function (event) {
    if (!event.target || event.target.type !== 'checkbox') return;
    var picked = cards.filter(function (card) {
      var box = card.querySelector('input');
      return box && box.checked && !card.hidden;
    });
    if (picked.length > 4) {
      event.target.checked = false;
      picked = picked.filter(function (card) { return card.querySelector('input').checked; });
    }
    panel.replaceChildren();
    if (picked.length < 2) return;
    var table = document.createElement('table');
    var head = document.createElement('tr');
    var corner = document.createElement('th');
    corner.textContent = 'Area';
    head.appendChild(corner);
    picked.forEach(function (card) {
      var cell = document.createElement('th');
      cell.textContent = card.querySelector('a').textContent;
      head.appendChild(cell);
    });
    table.appendChild(head);
    areas.forEach(function (key) {
      var row = document.createElement('tr');
      var name = document.createElement('th');
      name.textContent = key;
      row.appendChild(name);
      picked.forEach(function (card) {
        var cell = document.createElement('td');
        cell.textContent = card.getAttribute('data-' + key) === '1' ? 'Included' : 'Not available';
        row.appendChild(cell);
      });
      table.appendChild(row);
    });
    panel.appendChild(table);
  });
  var packed = JSON.parse(document.getElementById('compare-data').textContent);
  document.getElementById('compare-go').addEventListener('click', function () {
    var html = '';
    cards.forEach(function (card) {
      var box = card.querySelector('input');
      if (!box || !box.checked) return;
      html += packed[card.getAttribute('data-company')] || '';
    });
    document.getElementById('comparison').innerHTML = html;
  });
})();
</script>'''
