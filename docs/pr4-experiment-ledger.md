# PR4 experiment ledger

Preregistered before implementation, 2026-10-08. Target: a valid repeatable
official run above 80, with no wrong-company publication. Local scores cannot
establish that outcome. Planned score allocation remains 34/50 coverage,
28/30 evidence, 12/12 synthesis and 8/8 interaction, not a forecast or award.

| Experiment | Prediction before execution | Failure condition |
| --- | --- | --- |
| Frozen registry identity plus external routes | 100/100 terminal outputs; zero entity requests; supported frozen identity survives entity endpoint outage | Any missing identity, silent drop or wrong-company evidence |
| CSV and JSONL snapshot support | Explicit zero survives; missing stays null; corruption, duplicate subject and forged projection rejected | Any manufactured value or unverifiable selected row |
| Published claims contract | Website field becomes official_website; refresh keeps the same internal slots; replay has zero value changes | Alias collision, lost evidence, duplicate slots or false changes |
| Supplied cutoff | Future postings and dated activity excluded relative to supplied cutoff; acquisition timestamp retained | Current date silently replaces cutoff |
| Shard and resource boundary | Every supplied identity retained in order for 100/300/1100 input tests, extended to the board's 1500; each shard has independent 2000-request/2700-second ledger | Budget reset inside a shard, partial artifact marked complete, missing terminal rows |
| Product search, comparison and verification | Name and number search; two-company facts and unknowns compared; summary facts link to retained evidence on desktop and mobile | Unsupported summary, raw null shown as zero, missing evidence link or horizontal overflow |
| Representative live frozen shard | Zero automated unsupported publications, within organizer limits; no minimum recall forecast | Any unsupported publication or exceeded resource ceiling |
| Registered workplace names as NAV retrieval leads | A brand-named workplace fixture previously missed becomes one checked job; an identically named other-company fixture remains rejected; at most three details attempted | Brand name substitutes for exact employer bridge, or additional unbounded feed/detail work |
| Frozen registered email domain as website lead | Fixture with no website and non-derivable legal name becomes a verified website; accountant-domain counterexample stays unpublished; generic mail providers skipped | Email domain counts as ownership, more than six HTML attempts, or registry source zero overrides an explicit unregistered employee flag |

Checker implementations stay separate from extraction. Automated source audits
are not independent human labels. Preserve failed observations and exact head
hashes below; inspect results before promoting any coverage claim.

## Observations

### Initial full CSV failure, then repair

The first real archive run at local `013c921` / remote `22690f8` failed all 100
companies before networking. Header-only CSV sniffing inferred `doublequote=False`;
record 407, with an escaped quoted name, appeared to have an extra column. No
identity or external fact was published. The prediction failed. Force the standard
CSV doubled-quote convention in both independent parsers, retain every original
column, and test a quoted semicolon name. Repaired remote head `bd0e323` completed
the same archive. Archive SHA-256:
`5daebdf852b4a84db2ae2888f44147fc94d43230ab4cd6999bbe9c20e175af18`;
compressed 154,916,581 bytes, expanded 842,840,388 bytes.

### Same-code local outage and hosted source acquisition

At repaired code hash
`3d66dd712f54b8d9bc887f694e552b0a6124b0d7caf01269ab97d9dc88ed810b`,
the local run completed 100/100 with zero failed companies and an independent
source audit. All optional acquisitions failed locally with DNS errors: 1,044
outbound attempts, zero response bytes, $0 spend, 391,110 ms including launch and
audit. It retained 715 frozen facts and made zero entity requests. This is
outage-survival evidence, not external recall. Output hash:
`c17554a12cf52e5dedbad5ac5875a4a55b1820fdf7ad646a8a3ad695ad8d4671`.

The same application code in hosted run
[37843208235](https://github.com/GunaPalanivel/Shirushi/actions/runs/37843208235)
completed 100/100 with zero failed companies and a passing source audit in
588,441 ms including audit. It used 829 attempts, 13,882,624 response bytes and $0;
100 companies had supported financial history and 78 had operating locations.
Roles yielded 289 facts; accounts yielded 2,467; workplaces yielded 83. It still
had **zero supported website/business/jobs company coverage** and 187 failed
source attempts. NAV bootstrap timed out. No population recall or official
score follows from the source audit. Hosted output hash:
`2c21412d2e71372aa752d0fa4c28be4c2981eb0f1bee64970305343096f827ed`.

### Browser and failure-report counterexamples

The first hosted browser check passed desktop but failed mobile: an author
stylesheet's `display: block` overrode the browser's `[hidden]` behavior, leaving
100 filtered rows visible instead of one. Add an explicit `[hidden]` rule; keep
the original desktop/390/320 acceptance check unchanged.

The timed-out NAV bootstrap also exposed a cached-error bug: every company
prepended the same error prefix again. Cache the complete reason once. A
100-call regression requires a constant reason and one acquisition. Preserve
the actual timeout; this repair improves diagnostics and does not recover jobs.
Robots acquisition errors now retain the underlying transport reason while
keeping the access gate unchanged.

### Revised cold boundary

Pinned Python 3.12.12 passed 179 tests before final publication, six configuration
checks, compilation and whitespace validation. Cold published-contract runs at
100, 300, 1100 and 1500 retained all ordered identities with 1/3/11/15 independently
limited shards. Same-snapshot 100-company replay had zero value changes and zero
history growth. Refresh from the previous 100 into a supplied 1100-company batch
also had zero false value changes. These are synthetic contract exercises.

The revised resource guard allocates 2 GB virtual address space per supervisor
and 8 GB for its worker, at most 14 GB across the four controlled processes;
it retains the eight-CPU ceiling, shared 8 GB snapshot ceiling and 0.5 GB artifact
ceiling. Final exact-head hosted results must be checked separately from the
earlier source run. No claim of 80+ is authorized by these observations.

### Final hosted head and repeatable discovery failure, 9 October review

At `808f167`, workflow [37846382273](https://github.com/GunaPalanivel/Shirushi/actions/runs/37846382273)
completed with nine successful jobs and two failed NAV company-gain jobs. Both
gain jobs completed their outputs during a feed-bootstrap timeout, but established
no gain. These failures remain visible; support-only success is not a recall gate.
The frozen live shard returned 100/100, passed its source audit and used 828
attempts, $0 and 587,544 ms including launch and audit. Supported company coverage
was people 100, finance 100 and operating locations 78; website/business/jobs
coverage remained zero. Website diagnostics separate 66 companies without an
acquired page from 34 with pages but no verified website (227 candidates, 74 pages,
44 identity rejections). These are acquisition-stage observations, not independent
labels of available opportunities.

The combined shard returned 100/100 with 1,134 attempts, $0 and 868,062 ms. Browser
acceptance passed at 1440/390/320 pixels. These exact-head results replace the
earlier head's measurements for release review, without erasing failed runs.

Prediction before the discovery diagnostic repair: after one anonymous-provider
quota rejection, a 100-company replay makes one search attempt, preserves bounded
legal-name fallback and keeps the cached reason constant. The old code added one
`Anonymous discovery unavailable:` prefix per company. Cache the reason only on
the initial blocked failure, matching the already repaired NAV behavior. The
extended regression and all 179 tests pass locally on Python 3.12.14; six config
checks and whitespace validation pass. This is a diagnostic repair with no
predicted coverage gain; pinned 3.12.12 hosted checking remains separate.

Next experiment gate: review fixed source opportunities independently, distinguish
candidate/acquisition loss from legal-proof loss, predict newly covered companies
before tuning, and compare under the same request/time budget. Do not relax exact
identity proof to turn 34 rejected companies into apparent coverage. No official
score, private wire confirmation or paid-provider provisioning has been received.
