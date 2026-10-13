"""Host data for website-ownership proofs: public suffixes, shared platforms and directories.

Sources (fetched 2026-10-13):
* NORID_GEOGRAPHIC_AND_CATEGORY: ASCII second-level `.no` entries of the ICANN section of the Public Suffix List
  (https://publicsuffix.org/list/public_suffix_list.dat, section "no", Norid geographical and category second-level
  domains: municipalities, old county abbreviations, kommune, herad, museum, vgs, priv, dep, mil, ...). 550 entries.
* NORWEGIAN_COUNTIES and `fylke`: current county names added by hand because the list predates the 2020-2024 county
  reforms (vestland.no, viken.no, ...); a county domain belongs to the public sector, never to one company.
* SHARED_DOMAINS: mailbox providers and site-builder/hosting platforms where unrelated tenants share one registrable
  domain. Entries listed in the Public Suffix List private section (github.io, gitlab.io, netlify.app, vercel.app, pages.dev,
  herokuapp.com, blogspot.com, myshopify.com, notion.site, carrd.co, wixsite.com, webflow.io, azurewebsites.net, web.app,
  framer.app, wixstudio.io) come from there; the others (medium.com, substack.com, notion.so, linktr.ee,
  sites.google.com, mystrikingly.com, strikingly.com, weebly.com, jimdosite.com, jimdofree.com, squarespace.com, wix.com,
  godaddysites.com, business.site, wordpress.com, tumblr.com, ucoz.com, 000webhostapp.com) are platform domains named by
  the project coordinator or review findings; mailbox providers are the common free webmail domains.
* PATH_TENANT_HOSTS: platforms whose tenant sits in the URL path, so the host root is never one company's site.
"""

NORID_GEOGRAPHIC_AND_CATEGORY = """
aa aarborte aejrie afjord agdenes ah aknoluokta akrehamn al alaheadju alesund algard alstahaug alta
    alvdal amli amot andasuolo andebu andoy ardal aremark arendal arna aseral asker askim askoy askvoll
    asnes audnedal aukra aure aurland aurskog-holand austevoll austrheim averoy badaddja bahcavuotna
    bahccavuotna baidar bajddar balat balestrand ballangen balsfjord bamble bardu barum batsfjord
    bearalvahki beardu beiarn berg bergen berlevag bievat bindal birkenes bjerkreim bjugn bodo bokn
    bomlo bremanger bronnoy bronnoysund brumunddal bryne bu budejju bygland bykle cahcesuolo davvenjarga
    davvesiida deatnu dep dielddanuorri divtasvuodna divttasvuotna donna dovre drammen drangedal drobak
    dyroy egersund eid eidfjord eidsberg eidskog eidsvoll eigersund elverum enebakk engerdal etne
    etnedal evenassi evenes evje-og-hornnes farsund fauske fedje fet fetsund fhs finnoy fitjar fjaler
    fjell fla flakstad flatanger flekkefjord flesberg flora floro fm folkebibl folldal forde forsand
    fosnes frana fredrikstad frogn froland frosta froya fuoisku fuossko fusa fylkesbibl fyresdal
    gaivuotna galsa gamvik gangaviika gaular gausdal giehtavuoatna gielda gildeskal giske gjemnes
    gjerdrum gjerstad gjesdal gjovik gloppen gol gran grane granvin gratangen grimstad grong grue gulen
    guovdageaidnu ha habmer hadsel hagebostad halden halsa hamar hamaroy hammarfeasta hammerfest hapmir
    haram hareid harstad hasvik hattfjelldal haugesund hemne hemnes hemsedal herad hitra hjartdal
    hjelmeland hl hm hobol hof hokksund hol hole holmestrand holtalen honefoss hornindal horten hoyanger
    hoylandet hurdal hurum hvaler hyllestad ibestad idrett inderoy iveland ivgu jan-mayen jessheim
    jevnaker jolster jondal jorpeland kafjord karasjohka karasjok karlsoy karmoy kautokeino kirkenes
    klabu klepp kommune kongsberg kongsvinger kopervik kraanghke kragero kristiansand kristiansund
    krodsherad krokstadelva kvafjord kvalsund kvam kvanangen kvinesdal kvinnherad kviteseid kvitsoy
    laakesvuemie lahppi langevag lardal larvik lavagis lavangen leangaviika lebesby leikanger leirfjord
    leirvik leka leksvik lenvik lerdal lesja levanger lier lierne lillehammer lillesand lindas lindesnes
    loabat lodingen lom loppa lorenskog loten lund lunner luroy luster lyngdal lyngen malatvuopmi
    malselv malvik mandal marker marnardal masfjorden masoy matta-varjjat meland meldal melhus meloy
    meraker midsund midtre-gauldal mil mjondalen mo-i-rana moareke modalen modum molde mosjoen moskenes
    moss mr muosat museum naamesjevuemie namdalseid namsos namsskogan nannestad naroy narviika narvik
    naustdal navuotna nedre-eiker nesna nesodden nesoddtangen nesseby nesset nissedal nittedal nl nord-
    aurdal nord-fron nord-odal norddal nordkapp nordre-land nordreisa nore-og-uvdal notodden notteroy nt
    odda of oksnes ol omasvuotna oppdal oppegard orkanger orkdal orland orskog orsta osen oslo osoyro
    osteroy ostre-toten overhalla ovre-eiker oyer oygarden oystre-slidre porsanger porsangu porsgrunn
    priv rade radoy rahkkeravju raholt raisa rakkestad ralingen rana randaberg rauma re rendalen rennebu
    rennesoy rindal ringebu ringerike ringsaker risor rissa rl roan rodoy rollag romsa romskog roros
    rost royken royrvik ruovat rygge salangen salat saltdal samnanger sandefjord sandnes sandnessjoen
    sandoy sarpsborg sauda sauherad sel selbu selje seljord sf siellak sigdal siljan sirdal skanit
    skanland skaun skedsmo skedsmokorset ski skien skierva skiptvet skjak skjervoy skodje slattum smola
    snaase snasa snillfjord snoasa sogndal sogne sokndal sola solund somna sondre-land songdalen sor-
    aurdal sor-fron sor-odal sor-varanger sorfold sorreisa sortland sorum spjelkavik spydeberg st stange
    stat stathelle stavanger stavern steigen steinkjer stjordal stjordalshalsen stokke stor-elvdal stord
    stordal storfjord strand stranda stryn sula suldal sund sunndal suohkan surnadal svalbard sveio
    svelvik sykkylven tana tananger time tingvoll tinn tjeldsund tjielte tjome tm tokke tolga tonsberg
    torsken tr trana tranby tranoy troandin trogstad tromsa tromso trondheim trysil tvedestrand tydal
    tynset tysfjord tysnes tysvar uenorge ullensaker ullensvang ulstein ulvik unjarga utsira va vaapste
    vadso vaga vagan vagsoy vaksdal valle vang vanylven vardo varggat varoy vefsn vega vegarshei
    vennesla verdal verran vestby vestnes vestre-slidre vestre-toten vestvagoy vevelstad vf vgs vik
    vikna vindafjord voagat volda voss vossevangen
""".split()
NORWEGIAN_COUNTIES = ('agder', 'akershus', 'buskerud', 'finnmark', 'fylke', 'innlandet', 'more-og-romsdal', 'nordland',
                      'oslo', 'ostfold', 'rogaland', 'telemark', 'troms', 'trondelag', 'vestfold', 'vestland', 'viken')
PUBLIC_SUFFIXES = (frozenset(name + '.no' for name in NORID_GEOGRAPHIC_AND_CATEGORY)
                   | frozenset(name + '.no' for name in NORWEGIAN_COUNTIES)
                   | {'co.uk', 'ac.uk', 'com.au', 'com.no', 'org.no'})
# Registrations below these suffixes belong to municipalities, counties, schools, museums and similar public bodies.
PUBLIC_SECTOR_SUFFIXES = PUBLIC_SUFFIXES - {'co.uk', 'ac.uk', 'com.au', 'com.no', 'org.no'}
SHARED_DOMAINS = frozenset((
    'medium.com', 'substack.com', 'notion.site', 'notion.so', 'linktr.ee', 'google.com', 'mystrikingly.com',
    'strikingly.com', 'weebly.com', 'jimdosite.com', 'jimdofree.com', 'carrd.co', 'squarespace.com', 'wixsite.com',
    'wix.com', 'webflow.io', 'godaddysites.com', 'business.site', 'github.io', 'gitlab.io', 'netlify.app', 'vercel.app',
    'pages.dev', 'herokuapp.com', 'blogspot.com', 'wordpress.com', 'tumblr.com', 'ucoz.com', '000webhostapp.com',
    'myshopify.com', 'azurewebsites.net', 'web.app', 'framer.app', 'wixstudio.io', 'gmail.com', 'hotmail.com',
    'hotmail.no', 'outlook.com', 'outlook.no', 'yahoo.com', 'yahoo.no', 'online.no', 'live.com', 'live.no', 'icloud.com',
    'proton.me', 'protonmail.com'))
PATH_TENANT_HOSTS = ('medium.com', 'linktr.ee', 'sites.google.com', 'notion.so', 'notion.site', 'github.com',
                     'gitlab.com', 'linkedin.com', 'facebook.com', 'instagram.com', 'youtube.com', 'x.com',
                     'twitter.com')
