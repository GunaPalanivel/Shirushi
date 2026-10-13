"""Independent company-paragraph and post-publication evidence checks."""
import hashlib
import json
import re
from datetime import date
from urllib.parse import unquote, urlsplit

from .html_support import document
from .support import check_time


def ambiguous(value):
    return bool(re.search(r"[?:\"\u2018\u2019\u201c\u201d\u00ab\u00bb]|(?<!\w)'(?!\w)", value)
        or re.search(r'\b(?:not|ikke|never|aldri|none|ingen|hvis|dersom|if|unless|would|could|said|says|sier|'
            r'quoted|quote|sitert|omtalt|discussed|kunde|customer|behalf|vegne|'
            r'group|gruppen|konsern\w*|parent|subsidiar\w*|morselskap|datterselskap|jeg|my)\b', value, re.I))


def section_guards(page, node, loc, item, what):
    """Bounded-context, quote, label and support-span guards shared by named paragraph routes."""
    parents = [n for n in page.nodes if n['tag'] in ('div', 'section', 'article')
               and n['start'] < node['start'] and node['end'] < n['end']]
    bounded = [n for n in parents if len(n['text']) <= 3000]
    context = min(bounded, key=lambda n:n['end'] - n['start']) if bounded else None
    if any(tag not in ('html', 'body') for tag in node['ancestors']) and context is None:
        raise ValueError('Audit ' + what + ' lacks bounded context')
    prefixes = [parent['text'].split(node['text'], 1)[0] for parent in parents]
    if any(re.search(r'["‘’“”«»]|(?<!\w)\x27(?!\w)|\b(?:hypothetical|scenario|imagine|suppose|forestill|false|fake|denied|benektet|usant|falsk)\b', prefix, re.I) for prefix in prefixes):
        raise ValueError('Audit ' + what + ' is in quoted context')
    labels = [n['text'] for n in page.nodes if n['end'] <= node['start']
              and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in parents)]
    if any(re.search(r'\b(?:hypothetical|scenario|false|fake|denied|benektet|usant|falsk)\b', label, re.I) for label in labels):
        raise ValueError('Audit ' + what + ' is in hypothetical or denial context')
    if any(re.fullmatch(r'(?:(?:our|the|a|vår[et]?)\s+|this\s+is\s+(?:an?\s+)?)?'
        r'(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|group|gruppen|konsern\w*|quoted|quote|speaker)'
        r'(?:\s+(?:story|record|case|example|profile|testimonial|context|description|scenario|statement|interview|services|activities|company|companies|structure|information|news))*[ .:!?]*', label, re.I) for label in labels):
        raise ValueError('Audit ' + what + ' belongs to another speaker context')
    support = {}
    if context:
        if (loc.get('container_start'),loc.get('container_end')) != (context['start'],context['end']):
            raise ValueError('Audit ' + what + ' section locator mismatch')
        support['section_context'] = page.source[context['start']:context['end']]
    if item.get('support_spans') != support:
        raise ValueError('Audit ' + what + ' support mismatch')
    return context


LEGAL_FORMS = ('AS', 'ASA', 'SA', 'ANS', 'DA', 'BA', 'NUF', 'ENK', 'KS')
ADVERB = r'(?:hovedsakelig|hovedsaklig|primært|blant\s+annet|også|alltid|spesielt)'
ACTIVITY = (r'(?:' + ADVERB + r'\s+)*(?:tilbyr|leverer|produserer|lager|utvikler|selger|bygger|installerer|utfører|'
            r'designer|distribuerer|importerer|rehabiliterer|driver\s+med|(?:arbeider|jobber)\s+(?:' + ADVERB + r'\s+)?med|'
            r'har\s+siden\s+[0-9]{4}\s+(?:produsert|levert|utviklet|solgt|bygget|installert)|'
            r'offers|provides|supplies|manufactures|produces|develops|delivers|sells|designs|builds|distributes)\b')
WORD = r'(?:[^\W\d_]|-)'
MODIFIER = (r'(?!(?:of|a|an|for|to|in|at|on|with|by|from|and|or|av|til|i|på|med|fra|den|det|de|en|et|ett|og|eller)(?![\w-]))'
            + WORD + '+')
DEFINITION = (r'(?:er\s+(?:en|et|ett)\s+(?:' + MODIFIER + r'\s+){0,3}' + WORD + r'*(?:leverandør|produsent|selskap|firma|bedrift|'
              r'foretak|byår|distributør|entreprenør|team|verksted|konsulent|rådgiver|studio|forhandler|utvikler)(?:er|e)?|'
              r'is\s+(?:a|an)\s+(?:' + MODIFIER + r'\s+){0,3}(?:company|consultancy|manufacturer|supplier|provider|distributor|'
              r'agency|firm|developer|contractor))\b')
GENERIC = set('flere ulike forskjellige mange alle sine deres våre vårt kunder kunde kundene leverandører '
              'samarbeidspartnere tjenester tjeneste løsninger løsning produkter produkt virksomhet virksomheten '
              'bedrifter bedrift selskap selskaper selskapet firma kvalitet norge norske norsk hovedsakelig hovedsaklig '
              'primært spesielt også alltid blant annet services solutions products customers clients partners '
              'various several many their other quality high company '
              'nøye utvalgte utvalgt ledende global globale innovative innovativ innovativt dedikert dedikerte '
              'skreddersydd skreddersydde tilpasset tilpassede individuelt løsningsrettet bistand hjelp deltaker '
              'deltakere strategier profesjonell profesjonelle erfaren erfarne dyktig dyktige komplett komplette moderne '
              'fremtidsrettede bærekraftige helhetlig unik unike beste gode leading carefully selected professional '
              'dedicated tailored experienced modern comprehensive unique best good supplier suppliers innen innenfor over '
              'under mellom gjennom samt både eller hele hver fra from with that this into onto through between '
              'within your'.split())
OFF_TOPIC = {'personvern', 'personvernerklaering', 'personvernerklæring', 'privacy', 'cookie', 'cookies', 'vilkar',
             'vilkår', 'betingelser', 'salgsbetingelser', 'terms', 'conditions', 'legal', 'jobb', 'jobs', 'job',
             'karriere', 'career', 'careers', 'stilling', 'stillinger', 'ledige', 'aktuelt', 'nyheter', 'nyhet', 'news',
             'blogg', 'blog', 'presse', 'press'}


def split_sentences(text):
    parts, start = [], 0
    for m in re.finditer(r'(?<=[.!?])\s+', text):
        end = m.start() - 1
        if end >= 1 and text[end - 1].isalpha() and text[end - 1].isupper() and (end < 2 or not text[end - 2].isalpha()):
            continue
        if end >= 3 and text[end] == '.' and text[end - 1].isalpha() and text[end - 2] == '.' and text[end - 3].isalpha():
            continue
        parts.append(text[start:m.start()])
        start = m.end()
    return [part for part in parts + [text[start:]] if part]


def statement_kind(sentence, paragraph, name, subject):
    """Return 'activity' or 'definition' for a qualifying sentence, else raise ValueError."""
    name = ' '.join(name.split())
    words = name.split()
    forms = [name] + [' '.join(rest) for rest in (words[:-1] if words[-1:] and words[-1] in LEGAL_FORMS else [],
                                                    words[1:] if words[:1] and words[0] in LEGAL_FORMS else []) if len(' '.join(rest)) >= 4]
    start = next((m for form in sorted(set(forms), key=len, reverse=True)
                  if (m := re.match('(' + re.escape(form) + r')(?!\w)\s+', sentence, re.I))), None)
    if start is None:
        raise ValueError('Audit statement is not a business statement: no subject at start')
    after, remainder = sentence[start.end(1):], sentence[start.end():]
    predicate = re.match(ACTIVITY, remainder, re.I) or re.match(DEFINITION, remainder, re.I)
    if predicate is None:
        raise ValueError('Audit statement is not a business statement: no predicate after subject')
    if (re.search(r'[?:;"‘’“”«»]|(?<!\w)\x27|\x27(?!\w)', after)
            or re.search(r'\b(?:not|ikke|never|aldri|none|ingen|hvis|dersom|if|unless|would|could|said|says|sier|quoted|quote|'
                r'sitert|omtalt|discussed|kunde|customer|behalf|vegne|group|gruppen|jeg|my|controller|processor|'
                r'behandlingsansvarlig|databehandler|member|affiliate|holding|juridisk|partner|plaintiff|defendant|'
                r'shareholder|beneficiary|sponsor|example|joke)\b|\b(?:konsern|subsidiar|morselskap|datterselskap|medlem)\w*|'
                r'\bdel\s+av\b', after, re.I)
            or re.search(r'\b(?:while|but|whereas|although|because|since|when|however|meanwhile|mens|men|fordi)\b', after, re.I)
            or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', after)
            or re.search(r'false|fake|denied|benektet|usant|falsk|hypothetical|scenario', paragraph, re.I)):
        raise ValueError('Audit statement is not a business statement: rejected context')
    numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', sentence, re.I)
    if {re.sub(r'\D', '', n) for n in numbers} - {subject}:
        raise ValueError('Audit content has competing legal identifiers')
    kind = 'activity' if re.match(ACTIVITY, remainder, re.I) else 'definition'
    if kind == 'definition' and re.search(r'\b(?:som|which|that)\b(?!\s+(?:holder|leverer|tilbyr|driver|produserer|utfører|serves|'
                                          r'provides|offers|supplies|operates|produces|delivers|specializes)\b)', after, re.I):
        raise ValueError('Audit statement is not a business statement: relative clause does not preserve the subject')
    removed = remainder[predicate.end():] if kind == 'activity' else remainder[re.match(r'(?:er\s+(?:en|et|ett)|is\s+(?:a|an))\s+', remainder, re.I).end():]
    if len({w for w in re.findall(WORD + '+', removed.lower()) if len(w) >= 4 and w not in GENERIC}) < 2:
        raise ValueError('Audit statement is not a business statement: no concrete offering')
    return kind


def audit_content(subject, claim, item, receipt, raw, anchor):
    registered = anchor.get('hjemmeside', '')
    registered = urlsplit(registered if '://' in registered else 'https://' + registered).hostname
    actual = urlsplit(receipt['effective_url']).hostname
    if not registered or not actual or registered.removeprefix('www.') != actual.removeprefix('www.'):
        raise ValueError('Audit bounded content lacks registered host')
    page, loc, name = document(raw), item['locator'], anchor['navn']
    def located(start, end):
        if type(start) is not int or type(end) is not int:
            raise ValueError('Audit content locator type invalid')
        node = next((n for n in page.nodes if (n['start'], n['end']) == (start, end)), None)
        if node is None:
            raise ValueError('Audit content locator is hidden or unclosed')
        return node
    node = located(loc.get('html_start'), loc.get('html_end'))
    if page.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Audit content literal span mismatch')
    if item['extraction_method'] == 'named_company_definition_v1':
        kind = r'(?:[A-Za-z\u00c6\u00d8\u00c5\u00e6\u00f8\u00e5-]+(?:firma|selskap|kontor|bedrift|foretak)|consultant|consultancy|intermediary|supplier|provider|manufacturer|agency|broker|hotel|restaurant)'
        modifiers = r'(?:(?:independent|financial|modern|modern[et]?|norsk[et]?|norske|ledende|lokal[et]?|international|internasjonal[et]?|autorisert|authorized|authorised|registered|professional|global|regional|private|public|specialist|Norwegian)\s+){0,4}'
        sentence = re.split(r'(?<![A-Za-z]\.[A-Za-z]\.)(?<=[.!?])\s+', node['text'], maxsplit=1)[0]
        assertion = re.match(re.escape(name) + r'\s+(?:er\s+(?:en|et|ett)|is\s+(?:a|an))\s+' + modifiers + kind + r'\b', sentence, re.I)
        if (node['tag'] != 'p' or not 10 <= len(node['text']) <= 2000
                or not assertion
                or ambiguous(sentence[len(name):])
                or re.search(r'[;,:]', sentence[len(name):])
                or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', re.sub(re.escape(name), '', sentence, flags=re.I))
                or re.search(r'\b(?:controller|processor|behandlingsansvarlig|databehandler|member|affiliate|holding|juridisk|partner|plaintiff|defendant|shareholder|beneficiary|sponsor|example|joke)\b|\bdel\s+av\b', sentence[len(name):], re.I)
                or re.search(r'\b(?:false|fake|denied|benektet|usant|falsk|hypothetical|scenario)\b', node['text'], re.I)):
            raise ValueError('Audit definition is not an affirmative business assertion')
        complement = sentence[assertion.end():].strip()
        if (complement and not re.match(r'(?:[.!?]$|(?:and|og|for|of|in|at|with|av|i|p\u00e5|til|med|som|which|that)\b)', complement, re.I)):
            raise ValueError('Audit business-type head has an unsupported complement')
        if re.search(r'\b(?:while|but|whereas|although|because|since|when|however|meanwhile|mens|men|fordi)\b', complement, re.I):
            raise ValueError('Audit definition switches to an additional clause')
        if re.search(r'\b(?:som|which|that)\s+(?!(?:holder|leverer|tilbyr|driver|produserer|utf\u00f8rer|serves|provides|offers|supplies|operates|produces|delivers|specializes)\b)', complement, re.I):
            raise ValueError('Audit relative clause does not preserve the named subject')
        clauses = re.split(r'\b(?:and|og)\s+', sentence[len(name):], flags=re.I)[1:]
        if any(not re.fullmatch(modifiers + kind + r'[.!?]?', clause.strip(), re.I) for clause in clauses):
            raise ValueError('Audit definition contains another predicated clause')
        section_guards(page, node, loc, item, 'definition')
        expected, field, family, key = sentence, 'business_description', 'business_products', None
    elif item['extraction_method'] == 'registry_linked_business_statement_v1':
        if node['tag'] != 'p' or not 10 <= len(node['text']) <= 2000:
            raise ValueError('Audit statement is not an eligible paragraph')
        if any(token in OFF_TOPIC for segment in unquote(urlsplit(receipt['effective_url']).path).lower().split('/')
               for token in re.split(r'[-_.]', segment)):
            raise ValueError('Audit statement page kind is not a company description page')
        sentences = split_sentences(node['text'])
        if claim['value'] not in sentences:
            raise ValueError('Audit statement is not a paragraph sentence')
        kind = statement_kind(claim['value'], node['text'], name, subject)
        for earlier in sentences[:sentences.index(claim['value'])]:
            try:
                statement_kind(earlier, node['text'], name, subject)
            except ValueError:
                continue
            raise ValueError('Audit statement is not the first qualifying sentence')
        context = section_guards(page, node, loc, item, 'statement')
        if set(loc) != {'html_start', 'html_end'} | ({'container_start', 'container_end'} if context else set()):
            raise ValueError('Audit statement locator keys mismatch')
        sentence = expected = claim['value']
        field, family = ('business_description', 'business_products') if kind == 'definition' else ('product_service', 'business_products')
        key = None if kind == 'definition' else hashlib.sha256(expected.encode()).hexdigest()
    elif item['extraction_method'] == 'bounded_company_section_v1':
        intro = located(loc.get('subject_start'), loc.get('subject_end'))
        if node['tag'] != 'p' or intro['tag'] != 'p' or not 10 <= len(node['text']) <= 1000:
            raise ValueError('Audit content is not a bounded paragraph')
        combined = intro['text'] + (' ' + node['text'] if intro != node else '')
        if (ambiguous(combined) or re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', re.sub(re.escape(name), '', combined, flags=re.I))
                or not re.search(r'\b(?:vi|we)\s+(?:utf\u00f8rer|tilbyr|leverer|produserer|supply|provide|offer|manufacture|'
                    r'are\s+specialists|er\s+spesialister)\b|\bv\u00e5re\s+[^.!?]{1,150}\btilgjengelig\s+for\s+leie\b', node['text'], re.I)):
            raise ValueError('Audit paragraph lacks affirmative own-service statement')
        if intro == node:
            if not re.match(r'(?:' + re.escape(name) + r'\s+ble\s+etablert\s+i\s+(?:\u00e5r\s+)?[0-9]{4}\b|'
                            r'Velkommen\s+til\s+' + re.escape(name) + r'\s*,)', node['text'], re.I):
                raise ValueError('Audit inline paragraph does not introduce the subject')
        elif (not re.match(r'(?:Vi|We)\b', node['text'], re.I)
                or page.source[intro['end']:node['start']].strip()
                or not re.fullmatch(r'(?:M\u00f8t|Meet)\s+[^.!?]{2,100},\s+(?:leder\s+for|leader\s+for)\s+'
                    + re.escape(name) + r'[.]?', intro['text'], re.I)):
            raise ValueError('Audit adjacent paragraph subject/speaker mismatch')
        parents = [n for n in page.nodes if n['tag'] in ('div', 'section', 'article')
                   and n['start'] < intro['start'] and node['end'] < n['end']]
        bounded = [n for n in parents if len(n['text']) <= 3000]
        context = min(bounded, key=lambda n: n['start']) if bounded else None
        if (intro != node or any(t not in ('html', 'body') for t in node['ancestors'])) and context is None:
            raise ValueError('Audit paragraph context is unclosed')
        support = {'subject_context': page.source[intro['start']:intro['end']]}
        if context:
            if len(context['text']) > 3000 or (loc.get('container_start'), loc.get('container_end')) != (context['start'], context['end']):
                raise ValueError('Audit section context bounds mismatch')
            if re.search(r'["\u2018\u2019\u201c\u201d\u00ab\u00bb]|(?<!\w)\x27(?!\w)', context['text']):
                raise ValueError('Audit section contains quoted speaker context')
            headings = [n['text'] for n in page.nodes if n['tag'] in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
                        and n['end'] <= intro['start']
                        and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in parents)]
            if any(ambiguous(h) or re.search(r'\b(?:parent|subsidiary|morselskap|datterselskap)\b', h, re.I) for h in headings):
                raise ValueError('Audit section identifies another speaker')
            labels = [n['text'] for n in page.nodes if n['end'] <= intro['start']
                      and any(parent['start'] < n['start'] and n['end'] < parent['end'] for parent in parents)]
            if any(re.match(r'(?:(?:our|the|a|v\u00e5r[et]?)\s+|this\s+is\s+(?:an?\s+)?)?'
                            r'(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|group|gruppen|konsern\w*|quoted|quote|speaker)\b', label, re.I) for label in labels):
                raise ValueError('Audit enclosing label identifies a different speaker')
            support['section_context'] = page.source[context['start']:context['end']]
        if item.get('support_spans') != support:
            raise ValueError('Audit section supporting spans mismatch')
        expected = node['text']
        if intro == node:
            sentences = re.split(r'(?<=[.!?])\s+', expected)
            markers = r'\b(?:vi|we)\s+(?:utf\u00f8rer|tilbyr|leverer|produserer|supply|provide|offer|manufacture|are\s+specialists|er\s+spesialister)\b|\bv\u00e5re\s+[^.!?]{1,150}\btilgjengelig\s+for\s+leie\b'
            selected = next(i for i, sentence in enumerate(sentences) if re.search(markers, sentence, re.I))
            expected = ' '.join(sentences[selected:])
        field, family, key = 'product_service', 'business_products', hashlib.sha256(expected.encode()).hexdigest()
    elif item['extraction_method'] == 'dated_post_headline_v1':
        children = [n for n in page.nodes if node['start'] < n['start'] and n['end'] < node['end']]
        titles = [n for n in children if n['tag'] in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
                  and 'wp-block-post-title' in (n['attrs'].get('class') or '').split()]
        times = [n for n in children if n['tag'] == 'time']
        if node['tag'] != 'li' or 'wp-block-post' not in (node['attrs'].get('class') or '').split() or len(node['text']) > 2000 or len(titles) != 1 or len(times) != 1:
            raise ValueError('Audit post card title/date scope mismatch')
        title, time = titles[0], times[0]
        if (ambiguous(title['text']) or re.search(r'\b(?:false|fake|denied|benektet|usant|falsk|rykte)\b', node['text'], re.I)
                or not re.fullmatch(r'[^.!?]{2,100}\s+er\s+ansatt\s+som\s+daglig\s+leder\s+i\s+' + re.escape(name) + r'[.]?', title['text'], re.I)):
            raise ValueError('Audit post headline lacks exact named appointment')
        parent_dates = [n for n in children if 'wp-block-post-date' in (n['attrs'].get('class') or '').split()
                        and n['start'] < time['start'] and time['end'] < n['end']]
        if len(parent_dates) != 1:
            raise ValueError('Audit post time has no publication role')
        role = ' '.join(str(n['attrs'].get(k) or '') for n in (time, parent_dates[0]) for k in ('itemprop', 'class')) + ' ' + parent_dates[0]['text']
        if re.search(r'modified|updated|startdate|enddate|event|oppdatert|endret|arrangement', role, re.I):
            raise ValueError('Audit post time is not a publication date')
        prior_labels = [node['text'].split(time['text'], 1)[0]] if time['text'] else []
        if any(re.search(r'modified|updated|oppdatert|endret|event|arrangement', label, re.I) for label in prior_labels):
            raise ValueError('Audit preceding time label is not publication')
        headline_urls = [n['attrs'].get('href') for n in children if n['tag'] == 'a'
                         and title['start'] < n['start'] and n['end'] < title['end']]
        dated_urls = [n['attrs'].get('href') for n in children if n['tag'] == 'a'
                     and time['start'] < n['start'] and n['end'] < time['end']]
        if len(headline_urls) != 1 or headline_urls != dated_urls or not headline_urls[0]:
            raise ValueError('Audit post headline and date identify different articles')
        declared = time['attrs']['datetime']
        published = date.fromisoformat(declared) if len(declared) == 10 else check_time(declared).date()
        numeric = re.fullmatch(r'([0-9]{1,2})[.]([0-9]{1,2})[.]([0-9]{4})', time['text'])
        if numeric is None or published != date(int(numeric[3]), int(numeric[2]), int(numeric[1])) or published > check_time(receipt.get('evaluation_cutoff', receipt['retrieved_at'])).date():
            raise ValueError('Audit post publication date is ambiguous')
        expected = {'statement': title['text'], 'published_at': published.isoformat(), 'source_url': receipt['effective_url']}
        field, family = 'public_activity', 'jobs_dated_activity'
        key = hashlib.sha256((title['text'] + '\n' + published.isoformat()).encode()).hexdigest()
    else:
        raise ValueError('Audit unknown bounded content method')
    identity_text = (combined if item['extraction_method'] == 'bounded_company_section_v1' else
                     sentence if item['extraction_method'] in ('named_company_definition_v1', 'registry_linked_business_statement_v1')
                     else node['text'])
    numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', identity_text, re.I)
    if {re.sub(r'\D', '', n) for n in numbers} - {subject}:
        raise ValueError('Audit content has competing legal identifiers')
    encoded = json.dumps([subject, field, 'registry_linked_html', key, None], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if (claim['value'] != expected or claim['field'] != field or claim.get('scope') != 'registry_linked_html'
            or claim.get('family') != family or claim.get('item_key') != key or claim.get('period') is not None
            or claim['claim_id'] != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Audit bounded content value or identity mismatch')
