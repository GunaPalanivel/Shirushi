"""Public-sector `.no` suffix data for the legal contact block audit (data only, no logic).

The Public Suffix List is MPL-2.0. This module keeps the `.no` second-level names, not the whole list.

Source: the second-level `.no` entries of the Public Suffix List ICANN section (downloaded 2026-10-13 from
https://publicsuffix.org/list/public_suffix_list.dat) as published in the legal-contact-block spec amendment, plus the
current counties. A host below one of these belongs to a municipality, county or category registry, not to one company.
"""

NO_SECOND_LEVEL = """
    aa aarborte aejrie afjord agdenes agder ah akershus aknoluokta akrehamn al alaheadju alesund algard
    alstahaug alta alvdal amli amot andasuolo andebu andoy ardal aremark arendal arna aseral asker askim
    askoy askvoll asnes audnedal aukra aurdal aure aurland aurskog-holand austevoll austrheim averoy
    badaddja bahcavuotna bahccavuotna baidar bajddar balat balestrand ballangen balsfjord bamble bardu barum
    batsfjord bearalvahki beardu beiarn berg bergen berlevag bievat bindal birkenes bjerkreim bjugn bodo
    bokn bomlo bremanger bronnoy bronnoysund brumunddal bryne bu budejju buskerud bygland bykle cahcesuolo
    davvenjarga davvesiida deatnu dep dielddanuorri divtasvuodna divttasvuotna donna dovre drammen drangedal
    drobak dyroy egersund eid eidfjord eidsberg eidskog eidsvoll eigersund elverum enebakk engerdal etne
    etnedal evenassi evenes evje-og-hornnes farsund fauske fedje fet fetsund fhs finnmark finnoy fitjar
    fjaler fjell fla flakstad flatanger flekkefjord flesberg flora floro fm folkebibl folldal forde forsand
    fosnes frana fredrikstad frogn froland frosta froya fuoisku fuossko fusa fylke fylkesbibl fyresdal
    gaivuotna galsa gamvik gangaviika gaular gausdal giehtavuoatna gielda gildeskal giske gjemnes gjerdrum
    gjerstad gjesdal gjovik gloppen gol gran grane granvin gratangen grimstad grong grue gulen guovdageaidnu
    ha habmer hadsel hagebostad halden halsa hamar hamaroy hammarfeasta hammerfest hapmir haram hareid
    harstad hasvik hattfjelldal haugesund hemne hemnes hemsedal herad hitra hjartdal hjelmeland hl hm hobol
    hof hokksund hol hole holmestrand holtalen honefoss hornindal horten hoyanger hoylandet hurdal hurum
    hvaler hyllestad ibestad idrett inderoy innlandet iveland ivgu jan-mayen jessheim jevnaker jolster
    jondal jorpeland kafjord karasjohka karasjok karlsoy karmoy kautokeino kirkenes klabu klepp kommune
    kongsberg kongsvinger kopervik kraanghke kragero kristiansand kristiansund krodsherad krokstadelva
    kvafjord kvalsund kvam kvanangen kvinesdal kvinnherad kviteseid kvitsoy laakesvuemie lahppi langevag
    lardal larvik lavagis lavangen leangaviika lebesby leikanger leirfjord leirvik leka leksvik lenvik
    lerdal lesja levanger lier lierne lillehammer lillesand lindas lindesnes loabat lodingen lom loppa
    lorenskog loten lund lunner luroy luster lyngdal lyngen malatvuopmi malselv malvik mandal marker
    marnardal masfjorden masoy matta-varjjat meland meldal melhus meloy meraker midsund midtre-gauldal mil
    mjondalen mo-i-rana moareke modalen modum molde more-og-romsdal mosjoen moskenes moss mr muosat museum
    naamesjevuemie namdalseid namsos namsskogan nannestad naroy narviika narvik naustdal navuotna
    nedre-eiker nesna nesodden nesoddtangen nesseby nesset nissedal nittedal nl nord- nord-fron nord-odal
    norddal nordkapp nordland nordre-land nordreisa nore-og-uvdal notodden notteroy nt odda of oksnes ol
    omasvuotna oppdal oppegard orkanger orkdal orland orskog orsta osen oslo osoyro osteroy ostfold
    ostre-toten overhalla ovre-eiker oyer oygarden oystre-slidre porsanger porsangu porsgrunn priv rade
    radoy rahkkeravju raholt raisa rakkestad ralingen rana randaberg rauma re rendalen rennebu rennesoy
    rindal ringebu ringerike ringsaker risor rissa rl roan rodoy rogaland rollag romsa romskog roros rost
    royken royrvik ruovat rygge salangen salat saltdal samnanger sandefjord sandnes sandnessjoen sandoy
    sarpsborg sauda sauherad sel selbu selje seljord sf siellak sigdal siljan sirdal skanit skanland skaun
    skedsmo skedsmokorset ski skien skierva skiptvet skjak skjervoy skodje slattum smola snaase snasa
    snillfjord snoasa sogndal sogne sokndal sola solund somna sondre-land songdalen sor- sor-fron sor-odal
    sor-varanger sorfold sorreisa sortland sorum spjelkavik spydeberg st stange stat stathelle stavanger
    stavern steigen steinkjer stjordal stjordalshalsen stokke stor-elvdal stord stordal storfjord strand
    stranda stryn sula suldal sund sunndal suohkan surnadal svalbard sveio svelvik sykkylven tana tananger
    telemark time tingvoll tinn tjeldsund tjielte tjome tm tokke tolga tonsberg torsken tr trana tranby
    tranoy troandin trogstad troms tromsa tromso trondelag trondheim trysil tvedestrand tydal tynset
    tysfjord tysnes tysvar uenorge ullensaker ullensvang ulstein ulvik unjarga utsira va vaapste vadso vaga
    vagan vagsoy vaksdal valle vang vanylven vardo varggat varoy vefsn vega vegarshei vennesla verdal verran
    vestby vestfold vestland vestnes vestre-slidre vestre-toten vestvagoy vevelstad vf vgs vik viken vikna
    vindafjord voagat volda voss vossevangen
""".split()

PUBLIC_SECTOR_SUFFIXES = frozenset(name + '.no' for name in NO_SECOND_LEVEL)
PUBLIC_SUFFIXES = PUBLIC_SECTOR_SUFFIXES | {'co.uk', 'ac.uk', 'com.au', 'com.no', 'org.no'}
