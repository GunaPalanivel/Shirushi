# What Shirushi can reuse from Builderr's results

Read on 8 October 2026: both complete index pages, linked result/rubric pages,
public builder profiles and three available implementations. The outcome is a
valid, repeatable Signalpost score above 80. A public profile, a completed run,
and a winning result are three different observations.

The project conversation and existing research emphasize correct attribution,
honest measurement, fast falsifiable iterations and a useful product. PR3's
green execution does not resolve its representative external-coverage failure.
Soham's reply gives concrete execution limits and points to the starter; it does
not award a score or promise a model/search credential. PR4 follows those limits
and requires supplied identity, cutoff and previous evidence.

Our central inference is that successful entrants align the *scored final
artifact* with the task and invest in its particular failure modes. Their
architecture alone does not establish causality. Private live strategies and
unavailable winning-version histories cannot be reconstructed from profile copy.

## What the two pages actually establish

[Winning agents](https://builderr.ai/winning-agents) combines a completed trading
winner, a dictation winner's contribution to RambleFix, and featured entries
that remain below their challenge bar. Arnav's +5.91% versus QQQ's -3.91% is one
16-live-day round. Sankeerth's separate English/Hindi-English paths shaped the
product; Arnav also contributed mixed-language terminology handling. These are
task-specific results, not evidence that an arbitrary general agent wins.

[Builders](https://builderr.ai/builders) is a directory: five claimed profiles
and a separate section of 47 reviewed entries from 33 participants. Claiming a
profile or sharing it changes neither score nor qualification. Arnav, Sankeerth,
Meet, Deepika and Sham span different tasks; many current trading strategies
remain private. Deepika's profile describes an active entry rather than a closed
winning result. The directory should guide primary-source inspection, not
serve as a leaderboard or an architecture popularity poll.

## Mechanisms, counterexamples and transfer

| Evidence inspected | Observed mechanism | Reuse in Shirushi | Limit or counterexample |
| --- | --- | --- | --- |
| [Arnav trading result](https://builderr.ai/trading-v0/winners/arnav), [submitted code and notes](https://github.com/builderr-ai/builderr-trading-round-1-winner) | Deterministic CASH/NEUTRAL/FULL states; momentum selection; sell before buying; cooldown, exposure taper and stops; no network or LLM calls | Explicit source/failure states, bounded exploration, stop acquiring before finalization, preserve supported facts across outages | One return window cannot identify the winning rule or predict future returns. Financial trading rules themselves are irrelevant here |
| [Sankeerth profile](https://builderr.ai/builders/sankeerth), [dictation rubric/results](https://builderr.ai/speech-to-text), [public code](https://github.com/San245o/builderr-speech-to-text) | Route English and mixed-language speech to different local engines; faithful final pass; empty-final fallback; record lane, timing and raw/final differences | Source-specific deterministic adapters; reliable final envelopes; separate acquisition, proposal, checking and output stages | 69.92 versus benchmark 58.77 is a six-clip check. Public PROGRESS notes a default-model/fine-tune deployment gap; the inspected head is not proven to be the frozen winning head |
| [Arnav profile](https://builderr.ai/builders/arnav) | One speech path for drafts and finals preserves mixed-language consistency | Keep stable semantic slots and original evidence across output aliases and refresh | A different design also clears the speech benchmark. Dual routing is not a universal requirement |
| [Meet profile](https://builderr.ai/builders/meet), [CCTV board](https://builderr.ai/kitchen-video), [implementation](https://github.com/meet252501/kitchen-CCTV) | Bounded frame sampling, visible timestamps, one model call for all questions on a video, explicit unknown fallback | Acquire shared sources once; reuse NAV feed and frozen archive; one terminal result per requested identity; source locators in final output | 6/6 and $0.038 per hour are six-question evidence, not broad accuracy or a final prize decision. The code estimates cost before the retry loop, so it does not establish a hard billed-attempt ceiling |
| [Vishal](https://builderr.ai/builders/vishal), [Sham](https://builderr.ai/builders/sham), [Harsimran](https://builderr.ai/builders/harsimran), [Rishchith](https://builderr.ai/builders/rishchith), [Vishwas](https://builderr.ai/builders/vishwas) | Isolation, warm fallback, compact inference or stronger finals can complete the run | Keep process supervision and reliable source-failure results | Completion still coexists with lost mixed-language facts, repetition, high final latency or missing finals. Reliability protects an opportunity to score; it does not create recall |

The CCTV implementation's timestamp annotation is inspectable, useful provenance;
its comment claiming to solve temporal blindness is not evidence of that claim.
Its answer normalization fills missing IDs but does not itself exclude duplicate
or extraneous IDs. Shirushi's boundary must enforce exact ordered membership,
rather than trusting a prompt or a fallback to do so.

The speech code's number normalization and repetition cleanup are task-specific
and potentially meaning-changing. Do not apply an analogous cleanup to company
financials, negation or entity names. Preserve the source token, reporting period,
currency and group/entity distinction; reject unsupported proposals.

## Validate against our actual work

| Area | Evidence before PR4 | PR4 response | What it cannot prove |
| --- | --- | --- | --- |
| Execution | PR3 final Linux and Windows checks passed; combined 100-company shards completed with zero automated unsupported publications | Supplied frozen anchors, growing batch shards, inherited Linux resource limits, bounded writes and an independently audited final artifact | Builderr eligibility and the private harness wire |
| External coverage | Development and validation representative cohorts each had zero verified website/business/jobs facts | Try frozen website/email-domain leads and verified workplace names; keep six-page and three-detail bounds and exact ownership/employer checks | Population recall, a paired 80-point gain or complete NAV absence |
| Positive route evidence | Inspected NAV-positive cohorts gained 7/6 business-covered companies and 20/19 jobs-covered companies, without losses; known Fristads path recovered catalogue facts | Preserve controls and independent source audits | Untouched validation: these examples were already inspected; conservative simultaneous intervals do not establish broad business recall |
| Synthesis / UX | Existing static table, summary and summary-only comparison | Direct evidence anchors in summaries; compare facts, unknowns, scopes, periods and freshness; number/name search; desktop/mobile acceptance | Awarding all 20 product points |
| Refresh | Semantic change detection and previous-source verification already exist | Website wire alias changes serialization only; supplied cutoff governs dated claims; frozen evidence is reverified on replay | Historical web state that a live source no longer exposes |

The strongest cross-task counterexample is Sankeerth: a dictation winner appears
on the current Signalpost board at 46.12 with 5.98/50 recall. This supports the
inference that importing a successful builder's architecture is insufficient.
Signalpost's current leader is 60.80; its best published recall component is
17.45/50 on a different, lower-total entry. The coverage problem is specific to
company sources and legal attribution.

## Work backwards from 80

With perfect remaining components, exceeding 80 still needs more than 30 of
50 recall points. With our planning allocation of 28 evidence, 12 synthesis and
8 UX, it needs more than 32 recall points; 34 gives an 82-point target. These
are arithmetic requirements, not an estimate of our current score.

Official family coverage weights company recall at 70% and fact recall at 30%.
Prioritize the first supported fact for a previously uncovered company-family
before adding a long catalogue for an already covered company. The private union
and family weights are unavailable, so local macro coverage cannot be relabeled
as official recall. Unknown opportunities are not negatives.

1. Make the submitted program runnable: supplied growing membership, frozen
   registry, explicit cutoff, exact final output and repeatable refresh. Resolve
   the public example versus nested starter-envelope discrepancy before freeze.
2. Freeze independent source opportunity labels before tuning the next route.
   Check both positives and plausible wrong-company counterexamples. Neither
   maker-output labels nor agreeing parsers constitute independent human review.
3. Use the PR4 acquisition funnel to locate the largest losses: no candidate,
   inaccessible/robots-blocked page, missing legal proof, or extraction failure.
   Predict new *company* gains, request use and precision before the run.
4. Compare one small repair against the fixed control on the same source snapshots
   and budget. Keep losses and failed experiments. Validate on new companies only
   after the mechanism freezes. Expand only a route with checked gains.
5. Obtain an official component breakdown from a frozen complete submission,
   repair its largest loss, and retain the earlier version for rollback. Daily
   mean ranking makes run reliability consequential. The final revision deadline
   from the mail is the end of 18 October UTC, not the Oct 21 challenge headline.

No model call is needed for the boundary, provenance or product work. Conditional
model proposals require an organizer-provisioned provider/env variable and a
declared per-attempt cost before freeze. The default evaluator command uses no
personal credentials and no paid API calls. A general research agent, a learned
planner and broader guesses are not supported by the measured bottleneck.

## Research provenance and reuse rights

Inspected public heads: trading `fbaf692b4a24a81e0560a249e13f79e67a3e8e0d`,
speech `5e440658c818d653e7b0eb23632e3d11206ca6a6`, CCTV
`db90e7988e963a90ff4d495fa6592033a0033c55`. A repository's current head is not
automatically its scored version. Trading's NOTICE grants no separate open-source
reuse licence. No competitor implementation or starter source was copied into
Shirushi; interface compatibility and the mechanisms above are implemented
independently. Shirushi itself still needs a selected licence before an OSS release.

Primary contract: [evaluation harness](https://builderr.ai/docs/signalpost-evaluation-harness.md),
[source requirements](https://builderr.ai/starter-briefs/signalpost-sources.md),
[starter archive](https://builderr.ai/signalpost-starter-kit.tar.gz),
[current Signalpost board](https://builderr.ai/challenges/signalpost).
Execution authority: Soham's 8 October email, retained as structured limits in
`organizer-run-limits.json`. The experiment ledger records predictions before
implementation and preserves inconvenient results.
