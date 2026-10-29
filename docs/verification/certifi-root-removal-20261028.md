# certifi compromised CA removal

Base: `44a9ff2cc97d1a6c0e1f114e79e86c0e6115dc39`.
Dependabot alert2 is open and critical for
[GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2),
with no withdrawal timestamp. The publisher recommends2026.10.19: it excludes the
compromised `emSign ECC Root CA - G3` while retaining unaffected emSign roots.
The published tag resolves to commit `662df63d7906df66f1f07c0751a3dfe9da14d914`.

The direct requirement changes from2026.7.22 to2026.10.19. Its universal lock was
regenerated with hashes. Every other lock byte, including its canonical command
header, remains unchanged.

The new regression exercises `tools.web_ingest._ssl_context()`. It failed with
the hash-verified old wheel because the compromised root was trusted. With the
patched private overlay, the focused consumer suite passed93 tests. The actual
consumer reported121 trusted CAs before and120 after; the three unaffected
emSign roots remain present, and ECC G3 is absent. DER fingerprints confirm
that every remaining trusted certificate is identical. Hostname checking and
`CERT_REQUIRED` remain enabled.

Using a sanitized environment and private HOME, the real consumer fetched
`https://pypi.org/pypi/certifi/2026.10.19/json` over verified HTTPS with status200.
No private authentication or shared environment changes were used.

[PyPI2026.10.19 metadata](https://pypi.org/pypi/certifi/2026.10.19/json) reports:

- Wheel SHA256: `42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b`.
- Source archive SHA256: `035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae`.

Both release artifacts are not yanked. The downloaded wheel digest was verified
before extracting the private overlay; the source archive digest was also
verified after download. No remote alert was dismissed and no
commit or push was made before root review.
