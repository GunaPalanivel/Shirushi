# Security policy

Shirushi has no supported official competition release yet. Offline and live runners perform source integrity, attribution, value support and refresh checks. Registry receipts and filesystem paths are trusted operator inputs. Hashes prove retained-byte integrity, not source-author authenticity.

Before the first public release, configure and verify a private vulnerability reporting channel and document its response policy here. No private GitHub reporting channel or security response SLA is currently claimed. Avoid putting credentials, sensitive company records or working exploit details in public issues.

The live fetcher accepts credential-free HTTPS on port 443, validates redirect host scope, rejects non-global or mixed DNS answers, connects to the validated address, and verifies TLS against the original hostname. It deliberately ignores environment proxy settings; environments without direct public DNS/network access cannot use this transport. Acquisition uses a whole-run request/time/body-byte budget, bounded retries and redirects, configured host spacing, and robots checks for company pages. Compressed responses are rejected. One network worker is currently effective even if a larger configuration ceiling is declared. A supervisor terminates blocked work while preserving checked checkpoints and producing every terminal slot.

Company pages require a retained BRREG website discovery anchor and explicit legal identifiers on the published structured facts. Parent, brand and subsidiary names never establish equivalent legal identity. Optional page failures remain visible as availability states. No authenticated service, paid search provider or secret is currently used.

The CI definition uses read-only repository permissions, full commit pins for third-party actions, and no persisted checkout credentials. It does not deploy, push commits or require company-source secrets. It tests pinned Linux/Windows runtimes and independently audits a fresh 100-company public-source run on Linux. Current status is recorded in the exact commit's hosted checks.
