"""Literal company descriptions and publication-bound post headlines."""
import re
from datetime import date
from urllib.parse import unquote, urlsplit

from .contracts import timestamp
from .html_sources import Sections, org_numbers


def uncertain(text):
    return bool(re.search(r"[?:\"\u2018\u2019\u201c\u201d\u00ab\u00bb]|(?<!\w)'(?!\w)", text)
        or re.search(r'\b(?:not|ikke|never|aldri|none|ingen|hvis|dersom|if|unless|would|could|'
            r'said|says|sier|quoted|quote|sitert|omtalt|discussed|kunde|customer|behalf|vegne|'
            r'group|gruppen|konsern\w*|parent|subsidiar\w*|morselskap|datterselskap|jeg|my)\b', text, re.I))


def closed_context(page, node):
    """The smallest bounded container of a paragraph, or (False, None) when its context is unsafe."""
    containers = [n for n in page.nodes if n['tag'] in {'div', 'section', 'article'}
                  and n['start'] < node['start'] and node['end'] < n['end']]
    contexts = [n for n in containers if len(n['text']) <= 3000]
    context = min(contexts, key=lambda n: n['end'] - n['start']) if contexts else None
    if any(tag not in {'html', 'body'} for tag in node['ancestors']) and context is None:
        return False, None
    prefixes = [parent['text'].split(node['text'], 1)[0] for parent in containers]
    if any(re.search(r'["‘’“”«»]|(?<!\w)\x27(?!\w)|\b(?:hypothetical|scenario|imagine|suppose|forestill|false|fake|denied|benektet|usant|falsk)\b', prefix, re.I) for prefix in prefixes):
        return False, None
    before = [n['text'] for n in page.nodes if n['end'] <= node['start']
              and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in containers)]
    if any(re.search(r'\b(?:hypothetical|scenario|false|fake|denied|benektet|usant|falsk)\b', label, re.I) for label in before):
        return False, None
    if any(re.fullmatch(r'(?:(?:our|the|a|vår[et]?)\s+|this\s+is\s+(?:an?\s+)?)?'
        r'(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|group|gruppen|konsern\w*|quoted|quote|speaker)'
        r'(?:\s+(?:story|record|case|example|profile|testimonial|context|description|scenario|statement|interview|services|activities|compan(?:y|ies)|structure|information|news))*[ .:!?]*', label, re.I) for label in before):
        return False, None
    return True, context


def paragraph_evidence(page, node, context):
    location = {'html_start': node['start'], 'html_end': node['end']}
    support = {}
    if context:
        location.update(container_start=context['start'], container_end=context['end'])
        support['section_context'] = page.source[context['start']:context['end']]
    return page.source[node['start']:node['end']], location, support


def definition_values(raw, subject, name):
    page = Sections(raw)
    kind = r'(?:[A-Za-z\u00c6\u00d8\u00c5\u00e6\u00f8\u00e5-]+(?:firma|selskap|kontor|bedrift|foretak)|consultant|consultancy|intermediary|supplier|provider|manufacturer|agency|broker|hotel|restaurant)'
    modifiers = r'(?:(?:independent|financial|modern|modern[et]?|norsk[et]?|norske|ledende|lokal[et]?|international|internasjonal[et]?|autorisert|authorized|authorised|registered|professional|global|regional|private|public|specialist|Norwegian)\s+){0,4}'
    for node in page.nodes:
        if node['tag'] != 'p' or not 10 <= len(node['text']) <= 2000:
            continue
        sentence = re.split(r'(?<![A-Za-z]\.[A-Za-z]\.)(?<=[.!?])\s+', node['text'], maxsplit=1)[0]
        assertion = re.match(re.escape(name) + r'\s+(?:er\s+(?:en|et|ett)|is\s+(?:a|an))\s+' + modifiers + kind + r'\b', sentence, re.I)
        if (not assertion
                or uncertain(sentence[len(name):]) or org_numbers(sentence) - {subject}
                or re.search(r'[;,:]', sentence[len(name):])
                or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', re.sub(re.escape(name), '', sentence, flags=re.I))
                or re.search(r'\b(?:controller|processor|behandlingsansvarlig|databehandler|member|affiliate|holding|juridisk|partner|plaintiff|defendant|shareholder|beneficiary|sponsor|example|joke)\b|\bdel\s+av\b', sentence[len(name):], re.I)
                or re.search(r'\b(?:false|fake|denied|benektet|usant|falsk|hypothetical|scenario)\b', node['text'], re.I)):
            continue
        complement = sentence[assertion.end():].strip()
        if (complement and not re.match(r'(?:[.!?]$|(?:and|og|for|of|in|at|with|av|i|p\u00e5|til|med|som|which|that)\b)', complement, re.I)):
            continue
        if re.search(r'\b(?:while|but|whereas|although|because|since|when|however|meanwhile|mens|men|fordi)\b', complement, re.I):
            continue
        if re.search(r'\b(?:som|which|that)\s+(?!(?:holder|leverer|tilbyr|driver|produserer|utf\u00f8rer|serves|provides|offers|supplies|operates|produces|delivers|specializes)\b)', complement, re.I):
            continue
        coordination = re.split(r'\b(?:and|og)\s+', sentence[len(name):], flags=re.I)[1:]
        if any(not re.fullmatch(modifiers + kind + r'[.!?]?', clause.strip(), re.I) for clause in coordination):
            continue
        safe, context = closed_context(page, node)
        if not safe:
            continue
        yield (sentence, *paragraph_evidence(page, node, context))
        return


LEGAL_FORM = r'(?:AS|ASA|SA|ANS|DA|BA|NUF|ENK|KS)'
ADVERB = r'(?:hovedsakelig|hovedsaklig|primært|blant\s+annet|også|alltid|spesielt)'
ACTIVITY = (r'(?:' + ADVERB + r'\s+)*(?:(?:tilbyr|leverer|produserer|lager|utvikler|selger|bygger|installerer|utfører|'
    r'designer|distribuerer|importerer|rehabiliterer|offers|provides|supplies|manufactures|produces|develops|'
    r'delivers|sells|designs|builds|distributes)\b|driver\s+med\b|(?:arbeider|jobber)\s+(?:' + ADVERB + r'\s+)?med\b|'
    r'har\s+siden\s+[0-9]{4}\s+(?:produsert|levert|utviklet|solgt|bygget|installert)\b)')
# Only adjectives may sit between the article and the head noun; a preposition makes it a relation ('tenant of').
MODIFIER = r'(?!(?:of|the|a|an|for|to|in|at|on|with|by|from|and|or|av|til|i|på|med|fra|den|det|de|en|et|ett|og|eller)\b)'
DEFINITION = (r'(?:er\s+(?:en|et|ett)\s+(?:' + MODIFIER + r'[^\W\d_][\w-]*\s+){0,3}[\w-]*(?:leverandør|produsent|selskap|firma|bedrift|'
    r'foretak|byrå|distributør|entreprenør|team|verksted|konsulent|rådgiver|studio|forhandler|utvikler)(?:er|e)?\b|'
    r'is\s+(?:a|an)\s+(?:' + MODIFIER + r'[A-Za-z-]+\s+){0,3}(?:company|consultancy|manufacturer|supplier|provider|distributor|'
    r'agency|firm|developer|contractor)\b)')
GENERIC = frozenset('''flere ulike forskjellige mange alle sine deres våre vårt kunder kunde kundene leverandører
    samarbeidspartnere tjenester tjeneste løsninger løsning produkter produkt virksomhet virksomheten bedrifter bedrift
    selskap selskaper selskapet firma kvalitet norge norske norsk hovedsakelig hovedsaklig primært spesielt også alltid
    blant annet services solutions products customers clients partners various several many their other quality high
    company nøye utvalgte utvalgt ledende global globale innovative innovativ innovativt dedikert dedikerte skreddersydd
    skreddersydde tilpasset tilpassede individuelt løsningsrettet bistand hjelp deltaker deltakere strategier profesjonell
    profesjonelle erfaren erfarne dyktig dyktige komplett komplette moderne fremtidsrettede bærekraftige helhetlig unik
    unike beste gode leading carefully selected professional dedicated tailored experienced modern comprehensive unique
    best good supplier suppliers
    innen innenfor over under mellom gjennom samt både eller hele hver fra from with that this into onto through between
    within your'''.split())
SENTENCES = re.compile(r'(?<![A-Za-z]\.[A-Za-z]\.)(?<!\s[A-ZÆØÅ]\.)(?<=[.!?])\s+')
# Pages whose paragraphs describe policies, vacancies or dated news rather than what the company is.
OFF_TOPIC = frozenset('''personvern personvernerklaering personvernerklæring privacy cookie cookies vilkar vilkår betingelser
    salgsbetingelser terms conditions legal jobb jobs job karriere career careers stilling stillinger ledige aktuelt nyheter
    nyhet news blogg blog presse press'''.split())


def off_topic(url):
    path = unquote(urlsplit(url).path).lower()
    return any(token in OFF_TOPIC for segment in path.split('/') for token in re.split(r'[-_.]+', segment))


def trade_name(name):
    """The registered name without ONE legal-form token: a trailing one, else a leading AS/ASA (registry spelling)."""
    name = name.strip()
    core = re.sub(r'\s+' + LEGAL_FORM + r'$', '', name, count=1)
    if core == name:
        core = re.sub(r'^(?:AS|ASA)\s+', '', name, count=1)
    return core if len(core) >= 4 else name


def statement_values(raw, subject, name, url=''):
    """First affirmative, concrete sentence a paragraph opens with the company's own (trade) name."""
    if off_topic(url):
        return
    page = Sections(raw)
    forms = sorted({name, trade_name(name)}, key=len, reverse=True)
    opening = re.compile('(?:' + '|'.join(re.escape(form) for form in forms) + r')(?!\w)\s+', re.I)
    for node in page.nodes:
        if node['tag'] != 'p' or not 10 <= len(node['text']) <= 2000:
            continue
        if re.search(r'\b(?:false|fake|denied|benektet|usant|falsk|hypothetical|scenario)\b', node['text'], re.I):
            continue
        for sentence in SENTENCES.split(node['text']):
            subject_match = opening.match(sentence)
            if not subject_match:
                continue
            rest = sentence[subject_match.end():]
            activity = re.match(ACTIVITY, rest, re.I)
            definition = None if activity else re.match(DEFINITION, rest, re.I)
            if not (activity or definition):
                continue
            tail = rest[activity.end():] if activity else re.sub(r'^(?:er\s+(?:en|et|ett)|is\s+(?:a|an))\s+', '', rest, flags=re.I)
            concrete = [w for w in re.findall(r'[^\W\d_]+(?:-[^\W\d_]+)*', tail) if len(w) >= 4 and w.lower() not in GENERIC]
            if (len(concrete) < 2 or uncertain(rest) or '\x3b' in rest or org_numbers(sentence) - {subject}
                    or (definition and re.search(r'\b(?:som|which|that)\s+(?!(?:holder|leverer|tilbyr|driver|produserer|utfører|'
                                                 r'serves|provides|offers|supplies|operates|produces|delivers|specializes)\b)', rest, re.I))
                    or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', rest)
                    or re.search(r'\b(?:datterselskap|morselskap)\w*', rest, re.I)
                    or re.search(r'\b(?:controller|processor|behandlingsansvarlig|databehandler|member|medlem\w*|affiliate|holding|'
                                 r'juridisk|partner|plaintiff|defendant|shareholder|beneficiary|sponsor|example|joke)\b|\bdel\s+av\b', rest, re.I)
                    or re.search(r'\b(?:while|but|whereas|although|because|since|when|however|meanwhile|mens|men|fordi)\b', rest, re.I)):
                continue
            safe, context = closed_context(page, node)
            if safe:
                yield ('product_service' if activity else 'business_description', sentence,
                       *paragraph_evidence(page, node, context))
                return
            break


def section_values(raw, subject, name):
    page = Sections(raw)
    paragraphs = sorted((n for n in page.nodes if n['tag'] == 'p'), key=lambda n: n['start'])
    service = r'\b(?:vi|we)\s+(?:utf\u00f8rer|tilbyr|leverer|produserer|supply|provide|offer|manufacture|are\s+specialists|er\s+spesialister)\b'
    rental = r'\bv\u00e5re\s+[^.!?]{1,150}\btilgjengelig\s+for\s+leie\b'
    for index, node in enumerate(paragraphs):
        if not 10 <= len(node['text']) <= 1000 or uncertain(node['text']):
            continue
        introduction = node
        inline = re.match(r'(?:' + re.escape(name) + r'\s+ble\s+etablert\s+i\s+(?:\u00e5r\s+)?[0-9]{4}\b|'
                          r'Velkommen\s+til\s+' + re.escape(name) + r'\s*,)', node['text'], re.I)
        if not inline:
            if index == 0 or not re.match(r'(?:Vi|We)\b', node['text'], re.I):
                continue
            introduction = paragraphs[index - 1]
            if (page.source[introduction['end']:node['start']].strip()
                    or not re.fullmatch(r'(?:M\u00f8t|Meet)\s+[^.!?]{2,100},\s+(?:leder\s+for|leader\s+for)\s+'
                        + re.escape(name) + r'[.]?', introduction['text'], re.I)):
                continue
        joined = introduction['text'] + (' ' + node['text'] if introduction != node else '')
        if (uncertain(joined) or org_numbers(joined) - {subject}
                or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', re.sub(re.escape(name), '', joined, flags=re.I))
                or not (re.search(service, node['text'], re.I) or re.search(rental, node['text'], re.I))):
            continue
        containers = [n for n in page.nodes if n['tag'] in {'div', 'section', 'article'}
                      and n['start'] < introduction['start'] and node['end'] < n['end']]
        bounded = [n for n in containers if len(n['text']) <= 3000]
        container = min(bounded, key=lambda n: n['start']) if bounded else None
        if introduction != node and container is None:
            continue
        if any(tag not in {'html', 'body'} for tag in node['ancestors']) and container is None:
            continue
        if container:
            if len(container['text']) > 3000:
                continue
            if re.search(r'["\u2018\u2019\u201c\u201d\u00ab\u00bb]|(?<!\w)\x27(?!\w)', container['text']):
                continue
            headings = [n['text'] for n in page.nodes if n['tag'] in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
                        and n['end'] <= introduction['start']
                        and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in containers)]
            if any(uncertain(h) or re.search(r'\b(?:parent|subsidiary|morselskap|datterselskap)\b', h, re.I) for h in headings):
                continue
            labels = [n['text'] for n in page.nodes if n['end'] <= introduction['start']
                      and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in containers)]
            if any(re.match(r'(?:(?:our|the|a|v\u00e5r[et]?)\s+|this\s+is\s+(?:an?\s+)?)?'
                            r'(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|group|gruppen|konsern\w*|quoted|quote|speaker)\b', label, re.I) for label in labels):
                continue
        location = {'html_start': node['start'], 'html_end': node['end'],
                    'subject_start': introduction['start'], 'subject_end': introduction['end']}
        support = {'subject_context': page.source[introduction['start']:introduction['end']]}
        if container:
            location.update(container_start=container['start'], container_end=container['end'])
            support['section_context'] = page.source[container['start']:container['end']]
        value = node['text']
        if inline:
            sentences = re.split(r'(?<=[.!?])\s+', value)
            first = next(i for i, sentence in enumerate(sentences)
                         if re.search(service, sentence, re.I) or re.search(rental, sentence, re.I))
            value = ' '.join(sentences[first:])
        yield value, page.source[node['start']:node['end']], location, support
        return


def post_values(raw, subject, name, cutoff):
    page = Sections(raw)
    for card in page.nodes:
        if card['tag'] != 'li' or 'wp-block-post' not in (card['attrs'].get('class') or '').split() or len(card['text']) > 2000:
            continue
        children = [n for n in page.nodes if card['start'] < n['start'] and n['end'] < card['end']]
        headings = [n for n in children if n['tag'] in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
                    and 'wp-block-post-title' in (n['attrs'].get('class') or '').split()]
        times = [n for n in children if n['tag'] == 'time']
        if len(headings) != 1 or len(times) != 1 or org_numbers(card['text']) - {subject}:
            continue
        heading, time = headings[0], times[0]
        if (uncertain(heading['text']) or re.search(r'\b(?:false|fake|denied|benektet|usant|falsk|rykte)\b', card['text'], re.I)
                or not re.fullmatch(r'[^.!?]{2,100}\s+er\s+ansatt\s+som\s+daglig\s+leder\s+i\s+'
                    + re.escape(name) + r'[.]?', heading['text'], re.I)):
            continue
        date_nodes = [n for n in children if 'wp-block-post-date' in (n['attrs'].get('class') or '').split()
                      and n['start'] < time['start'] and time['end'] < n['end']]
        if len(date_nodes) != 1:
            continue
        roles = ' '.join(str(n['attrs'].get(k) or '') for n in (time, date_nodes[0]) for k in ('itemprop', 'class')) + ' ' + date_nodes[0]['text']
        if re.search(r'modified|updated|startdate|enddate|event|oppdatert|endret|arrangement', roles, re.I):
            continue
        labels = [card['text'].split(time['text'], 1)[0]] if time['text'] else []
        if any(re.search(r'modified|updated|oppdatert|endret|event|arrangement', label, re.I) for label in labels):
            continue
        title_links = [n['attrs'].get('href') for n in children if n['tag'] == 'a'
                       and heading['start'] < n['start'] and n['end'] < heading['end']]
        date_links = [n['attrs'].get('href') for n in children if n['tag'] == 'a'
                      and time['start'] < n['start'] and n['end'] < time['end']]
        if len(title_links) != 1 or title_links != date_links or not title_links[0]:
            continue
        try:
            value = time['attrs']['datetime']
            published = date.fromisoformat(value) if len(value) == 10 else timestamp(value).date()
            written = re.fullmatch(r'([0-9]{1,2})[.]([0-9]{1,2})[.]([0-9]{4})', time['text'])
            if written is None or published != date(int(written[3]), int(written[2]), int(written[1])) or published > cutoff:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        yield heading['text'], published.isoformat(), page.source[card['start']:card['end']], {
            'html_start': card['start'], 'html_end': card['end']}
