"""Independent attribution and date reconstruction for retained news cards."""
import hashlib
import calendar
import re
from datetime import date
from urllib.parse import urlsplit

from .html_support import document
from .support import check_time


def audit_article(raw, subject, name, article, location, receipt, registered_url):
    page = document(raw)
    stem = re.sub(r'\s+AS$', '', name, flags=re.I)
    registered = urlsplit(registered_url if '://' in registered_url else 'https://' + registered_url).hostname
    actual = urlsplit(receipt['effective_url']).hostname
    if (not registered or not actual or registered.removeprefix('www.') != actual.removeprefix('www.')
            or stem == name or len(stem) < 5 or location.get('actor_alias') != stem
            or article['tag'] != 'article' or not 10 <= len(article['text']) <= 2000):
        raise ValueError('Audit dated article lacks exact source identity')
    numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))'
        r'\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])',
        ' '.join(n['text'] for n in page.nodes), re.I)
    if {re.sub(r'\D', '', number) for number in numbers} - {subject}:
        raise ValueError('Audit article source contains conflicting entities')
    copyright = (r'(?:\u00a9\s*(?:copyright\s*)?|copyright\s+)'
        r'(?:[0-9]{4}(?:\s*[-\u2013]\s*[0-9]{4})?\s*)?' + re.escape(name) + r'\s*[.]?')
    if any(n['tag'] == 'footer' and re.search(
            r'\b(?:not|ikke|photo\w*|image\w*|credit\w*|bilde\w*|foto\w*|publisher|utgiver)\b', n['text'], re.I)
           for n in page.nodes):
        raise ValueError('Audit footer copyright context is ambiguous')
    visible_footers = [n for n in page.nodes if n['tag'] == 'footer']
    footer_matches = [n for n in page.nodes if re.fullmatch(copyright, n['text'], re.I)
                      and any(f['start'] <= n['start'] and n['end'] <= f['end'] for f in visible_footers)]
    if not footer_matches:
        raise ValueError('Audit article shorthand has no legal publisher context')
    contained = [n for n in page.nodes if n['start'] > article['start'] and n['end'] < article['end']]
    if any(n['tag'] == 'article' for n in contained):
        raise ValueError('Audit article mixes nested news cards')
    if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", article['text'])
            or re.search(r'\b(?:false|fake|allegation|denied|benektet|rykte|usant|falsk|rumou?rs?|not|ikke|never|aldri|'
                r'said|says|sier|imagine|scenario|possibilit\w*|possible|hypothet\w*|forestill|mulig\w*|hvis|dersom|if|unless|would|could)\b', article['text'], re.I)):
        raise ValueError('Audit article contains denial or uncertain reporting')
    publication_dates = set()
    months = {m.lower(): i for i in range(1, 13) for m in (calendar.month_name[i], calendar.month_abbr[i])}
    headings = [n['start'] for n in contained if n['tag'] in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')]
    for child in contained:
        if child['tag'] == 'time' and child['attrs'].get('datetime'):
            role = ' '.join(str(child['attrs'].get(k) or '') for k in ('itemprop', 'class')) + ' ' + child['text']
            if ('footer' in child['ancestors']
                    or re.search(r'modified|updated|startdate|enddate|event|oppdatert|endret|arrangement', role, re.I)):
                continue
            if not child['text'] or not headings or child['end'] > min(headings):
                raise ValueError('Audit article has ambiguous time metadata')
            declared = child['attrs']['datetime']
            interpreted = date.fromisoformat(declared) if len(declared) == 10 else check_time(declared).date()
            numeric = re.fullmatch(r'([0-9]{1,2})[.]([0-9]{1,2})[.]([0-9]{4})', child['text'])
            written = re.fullmatch(r'([0-9]{1,2})\s+([A-Za-z]{3,9})\s+([0-9]{4})', child['text'])
            if numeric:
                visible = date(int(numeric[3]), int(numeric[2]), int(numeric[1]))
            elif written:
                visible = date(int(written[3]), months[written[2].lower()], int(written[1]))
            else:
                visible = date.fromisoformat(child['text'])
            if interpreted != visible:
                raise ValueError('Audit article visible date contradicts metadata')
            publication_dates.add(interpreted)
        if child['tag'] == 'span' and 'published' in (child['attrs'].get('class') or '').split():
            parts = re.fullmatch(r'Published\s+([A-Za-z]{3,9})\s+([0-9]{1,2}),\s+([0-9]{4})'
                r'(?:\s*\|\s*Last updated\s+.+)?', child['text'], re.I)
            if parts:
                publication_dates.add(date(int(parts[3]), months[parts[1].lower()], int(parts[2])))
    cutoff = check_time(receipt.get('evaluation_cutoff', receipt['retrieved_at'])).date()
    if len(publication_dates) != 1 or next(iter(publication_dates)) > cutoff:
        raise ValueError('Audit article lacks one valid publication date')
    published = next(iter(publication_dates)).isoformat()
    statements = [(n, text) for n in sorted(contained, key=lambda n: n['start'])
                  for text in re.split(r'(?<=[.!?])\s+', n['text'])]
    for child, statement in statements:
        if child['tag'] not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p') or not 10 <= len(statement) <= 1000:
            continue
        if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", statement)
                or re.search(r'\b(?:ikke|not|no|none|ingen|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|said|says|sier)\b', statement, re.I)):
            continue
        named_action = re.match(re.escape(stem) + r'\s+(?:joins|joined|has\s+been\s+acquired\s+by|'
            r'opened|launched|announced|signed|\u00e5pnet|lanserte|kunngjorde|signerte)\b', statement, re.I)
        named_delivery = re.match(r'L\u00f8sningen,\s+levert\s+av\s+' + re.escape(stem)
            + r'(?=\s*[,.;]|\s+i\s+samarbeid\b|$)', statement, re.I)
        if named_action or named_delivery:
            expected = {'statement': statement, 'published_at': published, 'source_url': receipt['effective_url']}
            key = hashlib.sha256((statement + '\n' + published).encode()).hexdigest()
            return expected, 'jobs_dated_activity', key
    raise ValueError('Audit article lacks an affirmative named company action')
