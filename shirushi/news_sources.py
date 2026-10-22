"""One dated_news claim per article: headline plus the datetime attribute text."""
import re

from .html_sources import Sections

FIELD = 'dated_news'
METHOD = 'dated_article_datetime_v1'
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
# article_values quote class and both denial lists. Not its verb list or its date collapse.
QUOTE = re.compile(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]")
DENIAL = re.compile(
    r'\b(?:false|fake|allegation|denied|benektet|rykte|usant|falsk|rumou?rs?|not|ikke|never|aldri|'
    r'said|says|sier|imagine|scenario|possibilit\w*|possible|hypothet\w*|forestill|mulig\w*|hvis|dersom|if|unless|would|could)\b',
    re.I)
DENIAL_SENTENCE = re.compile(
    r'\b(?:ikke|not|no|none|ingen|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|said|says|sier)\b',
    re.I)


def news_values(raw, url):
    """Dated articles on a page whose website the caller already accepted."""
    page = Sections(raw)
    for article in page.blocks:
        if article['tag'] != 'article':
            continue
        children = [node for node in page.nodes if article['start'] < node['start'] and node['end'] < article['end']]
        if any(node['tag'] == 'article' for node in children):
            continue
        text = article['text']
        if QUOTE.search(text) or DENIAL.search(text) or DENIAL_SENTENCE.search(text):
            continue
        times = [node for node in children if node['tag'] == 'time' and node['attrs'].get('datetime')]
        headings = [node for node in children if node['tag'] in HEADINGS and node['text']]
        if len(times) != 1 or not headings:
            continue
        published = times[0]['attrs']['datetime']
        if not isinstance(published, str):
            continue
        value = {'headline': headings[0]['text'], 'published_at': published, 'source_url': url}
        yield (FIELD, value, page.source[article['start']:article['end']],
               {'html_start': article['start'], 'html_end': article['end']}, {})
