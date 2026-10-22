"""Bounded dated assertions with corroborated legal-name shorthand."""
import re
from datetime import date

from .contracts import timestamp
from .html_sources import Sections, org_numbers
from .snapshots import digest

MONTHS = {name: number for number, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
MONTHS.update({name: number for number, name in enumerate(('january', 'february', 'march', 'april',
    'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'), 1)})


def displayed_date(text):
    numeric = re.fullmatch(r'([0-9]{1,2})[.]([0-9]{1,2})[.]([0-9]{4})', text)
    english = re.fullmatch(r'([0-9]{1,2})\s+([A-Za-z]{3,9})\s+([0-9]{4})', text)
    if numeric:
        return date(int(numeric[3]), int(numeric[2]), int(numeric[1]))
    if english:
        return date(int(english[3]), MONTHS[english[2].lower()], int(english[1]))
    return date.fromisoformat(text)


def article_values(raw, subject, legal_name, url, cutoff):
    # This is not arbitrary trading-name inference. The registered domain and
    # an exact legal-company copyright in its footer corroborate this shorthand.
    alias = re.sub(r'\s+AS$', '', legal_name, flags=re.I)
    if alias == legal_name or len(alias) < 5:
        return
    page = Sections(raw)
    if any(org_numbers(n['text']) - {subject} for n in page.nodes):
        return
    copyright = (r'(?:\u00a9\s*(?:copyright\s*)?|copyright\s+)'
        r'(?:[0-9]{4}(?:\s*[-\u2013]\s*[0-9]{4})?\s*)?' + re.escape(legal_name) + r'\s*[.]?')
    footers = [n for n in page.nodes if n['tag'] == 'footer']
    if any(re.search(r'\b(?:not|ikke|photo\w*|image\w*|credit\w*|bilde\w*|foto\w*|publisher|utgiver)\b', n['text'], re.I)
           for n in footers):
        return
    if not any(re.fullmatch(copyright, n['text'], re.I)
               and any(f['start'] <= n['start'] and n['end'] <= f['end'] for f in footers)
               for n in page.nodes):
        return
    for article in page.blocks:
        if article['tag'] != 'article' or not 10 <= len(article['text']) <= 2000:
            continue
        children = [n for n in page.nodes if article['start'] < n['start'] and n['end'] < article['end']]
        if any(n['tag'] == 'article' for n in children):
            continue
        if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", article['text'])
                or re.search(r'\b(?:false|fake|allegation|denied|benektet|rykte|usant|falsk|rumou?rs?|not|ikke|never|aldri|'
                    r'said|says|sier|imagine|scenario|possibilit\w*|possible|hypothet\w*|forestill|mulig\w*|hvis|dersom|if|unless|would|could)\b', article['text'], re.I)):
            continue
        headings = [n['start'] for n in children if n['tag'] in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}]
        dates = set()
        invalid = False
        for node in children:
            try:
                if node['tag'] == 'time' and node['attrs'].get('datetime'):
                    roles = ' '.join(str(node['attrs'].get(k) or '') for k in ('itemprop', 'class')) + ' ' + node['text']
                    if ('footer' in node['ancestors']
                            or re.search(r'modified|updated|startdate|enddate|event|oppdatert|endret|arrangement', roles, re.I)):
                        continue
                    if not node['text'] or not headings or node['end'] > min(headings):
                        invalid = True
                        continue
                    value = node['attrs']['datetime']
                    published = date.fromisoformat(value) if len(value) == 10 else timestamp(value).date()
                    if displayed_date(node['text']) != published:
                        invalid = True
                        continue
                    dates.add(published)
                elif (node['tag'] == 'span' and 'published' in (node['attrs'].get('class') or '').split()):
                    match = re.fullmatch(r'Published\s+([A-Za-z]{3,9})\s+([0-9]{1,2}),\s+([0-9]{4})'
                        r'(?:\s*\|\s*Last updated\s+.+)?', node['text'], re.I)
                    if match:
                        dates.add(date(int(match[3]), MONTHS[match[1].lower()], int(match[2])))
            except (ValueError, KeyError):
                invalid = True
        if invalid or len(dates) != 1 or next(iter(dates)) > cutoff:
            continue
        published = next(iter(dates)).isoformat()
        statements = [(node, sentence) for node in sorted(children, key=lambda n: n['start'])
                      for sentence in re.split(r'(?<=[.!?])\s+', node['text'])]
        for node, text in statements:
            if node['tag'] not in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'} or not 10 <= len(text) <= 1000:
                continue
            if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", text)
                    or re.search(r'\b(?:ikke|not|no|none|ingen|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|said|says|sier)\b', text, re.I)):
                continue
            action = re.match(re.escape(alias) + r'\s+(?:joins|joined|has\s+been\s+acquired\s+by|'
                r'opened|launched|announced|signed|\u00e5pnet|lanserte|kunngjorde|signerte)\b', text, re.I)
            delivery = re.match(r'L\u00f8sningen,\s+levert\s+av\s+' + re.escape(alias)
                + r'(?=\s*[,.;]|\s+i\s+samarbeid\b|$)', text, re.I)
            if not (action or delivery):
                continue
            value = {'statement': text, 'published_at': published, 'source_url': url}
            key = digest((text + '\n' + published).encode())
            yield ('public_activity', value, 'jobs_dated_activity', key,
                   page.source[article['start']:article['end']],
                   {'html_start': article['start'], 'html_end': article['end'], 'legal_name': legal_name,
                    'dated_article': True, 'actor_alias': alias})
            break
