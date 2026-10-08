# Source and reuse decisions

The [source register](../configs/source-policy.json) separates source classes from activated adapters. The offline runner supports the frozen local registry and saved official roles. Network is disabled in all local configurations. Conditional live sources require access receipts and adapter checks before activation; this register is not a fetcher or an authorization bypass.

The [official source policy](https://builderr.ai/starter-briefs/signalpost-sources.md) prefers official Norwegian records and verified company-owned pages. Each published fact still needs exact legal subject, durable permitted support, acquisition date, hash, extraction method and period when relevant. Official records anchor legal identity, not website ownership.

| Route | repository bootstrap decision | Activation evidence |
| --- | --- | --- |
| Frozen supplied registry | Enabled offline | Verified original input hashes and row identity |
| Saved official roles | Enabled offline | Fixed subject endpoint, matching response links, successful original receipt, NLOD 2.0 policy, timestamp, hash and role-context checks |
| Registry/roles/subunits API | Conditional | Exact endpoint terms, rate policy, safe request accounting and typed tests |
| Accounts API/PDF | Conditional | Access policy, units/year/entity scope checks and bounded fetch |
| Verified owned website/sitemap/feed | Conditional | Contextual exact identity, site terms/robots, redirect/network controls |
| Official announcements | Conditional | Access policy, dated event and exact subject; no duplicate syndication credit |
| Search | Disabled | Selected permitted provider, budget, refetched durable source; snippets are discovery only |
| Norid batch | Disabled | No batch permission established; do not infer access from lookup availability |
| NAV, patents, procurement | Disabled | Credentials/access route and measured evaluated-family overlap |
| Unofficial social/review connectors | Disabled | No permitted competition access established; promotional copy is not independent sentiment |

Source independence means origin independence, not number of URLs. A copied release has one origin family. Keep contradictions and scope; do not majority-vote a parent into the supplied entity. Changes trigger rechecking of affected evidence within budget; stronger old support is not overwritten by one weaker new observation.

The development collector is a separate, explicitly invoked acquisition tool, not a live runner adapter. Its twenty role and twenty accounts requests are declared as external cached inputs. Accounts bodies currently supply checker reference labels only; the maker has no accounts route. Registered roles do not prove employment, founding or ownership. See the [pilot protocol](batch-runner-hardening.md).

The local starter archive has no `LICENSE`, `LICENCE`, `COPYING` or `NOTICE` member. It is provided as an official learning reference, but explicit reuse terms were not established. No starter or competitor code is copied into the tracked implementation. Archive inspection and prior local synthetic probes inform independently authored tests. If reuse becomes useful, establish permission/licence and preserve notices first.

repository bootstrap has no third-party application dependencies. Python's runtime licence is a separate environment concern. Competitor README badges and GitHub licence detection are leads, not a verified grant covering every file. Do not infer that upstream code becomes reusable because it appears in a competitor repository.

Secrets will be server-side environment variables, never snapshots or tracked config. Original research and downloaded bodies stay under ignored `.idea/`; generated source data and reports stay under ignored `data/` and `out/`. A release will contain reviewed reports and declarations, not an indiscriminate dump of source material.
