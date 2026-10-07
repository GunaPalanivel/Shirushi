# Security policy

Shirushi has no public release and no supported production version yet. Local preparation tools perform configuration, contract and provenance checks; the network research agent is not implemented.

Before the first public release, configure and verify a private vulnerability reporting channel and document its response policy here. No private GitHub reporting channel or security response SLA is currently claimed. Avoid putting credentials, sensitive company records or working exploit details in public issues.

Security-sensitive contributions must preserve server-side secrets, exact-company attribution and evidence integrity. Network adapters must validate every redirect and destination, enforce source policy and resource limits, retain TLS verification, and reject private/loopback/link-local/metadata destinations. These adapter protections are planned, not implemented by the current boundary checker.

The CI definition uses read-only repository permissions, full commit pins for third-party actions, and no persisted checkout credentials. It does not deploy, push commits or require company-source secrets. Hosted CI has not run because local changes have not been pushed.
