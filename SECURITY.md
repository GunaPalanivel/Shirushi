# Security policy

Shirushi has no supported production release yet. The offline saved-company runner performs source integrity, attribution, value support and refresh checks; the network research agent is not implemented. Registry receipts and filesystem paths are trusted operator inputs. Hashes prove retained-byte integrity, not source-author authenticity.

Before the first public release, configure and verify a private vulnerability reporting channel and document its response policy here. No private GitHub reporting channel or security response SLA is currently claimed. Avoid putting credentials, sensitive company records or working exploit details in public issues.

Security-sensitive contributions must preserve server-side secrets, exact-company attribution and evidence integrity. Network adapters must validate every redirect and destination, enforce source policy and resource limits, retain TLS verification, and reject private/loopback/link-local/metadata destinations. These adapter protections are planned, not implemented by the current boundary checker.

The CI definition uses read-only repository permissions, full commit pins for third-party actions, and no persisted checkout credentials. It does not deploy, push commits or require company-source secrets. The previous hosted contract run failed during Windows runtime setup. The corrected workflow defines pinned Linux and Windows compatibility checks; its hosted result is pending at this milestone checkpoint.
