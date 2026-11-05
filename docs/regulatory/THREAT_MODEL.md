# Threat model (DRAFT, STRIDE)

Scope: the single-container product on a hospital server (web app, API, engine, database, DICOM/HL7 ports, outbound HIS link, identity providers, backups). **Assumes** the
hospital supplies the network perimeter, TLS reverse proxy, endpoint protection, patching of the host and Docker, physical security and a time source. Not a
penetration test: **no independent security test has been done** ([OWNER] priority).

## Assets
Patient identity and ECG data; signed reports; audit log; credentials and sessions; model files and thresholds; the audit key; backups.

## Trust boundaries
(1) browser ⇄ reverse proxy ⇄ API; (2) ECG devices ⇄ DICOM port / watched folder; (3) HIS ⇄ HL7 ports (both directions); (4) identity providers; (5) host file system / Docker; (6) build and supply chain; (7) backups off-server.

| Threat (STRIDE) | Where | Controls in place | Gap / next step |
|---|---|---|---|
| **S** Credential theft or guessing | login | scrypt, lockout (5 tries, 5 min), per-address block, password policy/expiry/history, optional TOTP, SSO | No breached-password check; TOTP not mandatory by default (can be required) |
| **S** Forged signing | sign | re-authentication, session idle timeout | See RISK R05 |
| **S** Rogue DICOM/HL7 sender | ports | address and AE-title allow-lists, optional mutual TLS, audit of refusals | Allow-lists empty by default (the hospital must set them); AE titles are not authentication |
| **S** Forged OIDC token | SSO | PKCE, RS256 signature, issuer/audience/nonce/expiry checked, forged-token tests | Depends on the provider's key rotation handling (JWKS refresh) |
| **T** Altered records or audit | database | keyed hash chain, anchors, role separation | Key beside the DB by default; anchors manual; DB admin can still alter ECG data itself (only the log is protected) |
| **T** Altered model/threshold files | engine | SHA-256 verification at start, thresholds bound to model, audit | Hash list lives in the same directory as the models: signing the release is not done |
| **T** Malicious input file | parsers | request size limits; machine-supplied XML (HL7 aECG, GE MUSE, Philips) is parsed with defusedxml (tests with entity-expansion and external-entity files); unreadable input refused with a reason; malformed-file tests | No fuzzing campaign for the binary readers (DICOM, SCP-ECG, EDF); PDF/image parsers (pypdf, Pillow) are third-party |
| **R** Repudiation | all actions | audit of sign-in, changes, views, exports, setting changes; per-person accounts | Shared accounts are a policy matter |
| **I** Data exposure | API, logs, e-mail | roles, TLS (proxy), HttpOnly SameSite cookies, CSP, no data in logs, e-mail without identifiers, error messages without internals | TLS is outside the container (hospital proxy); database not encrypted at rest by the product (hospital disk encryption); no field-level encryption |
| **I** Cross-site request / script | web app | CSRF header, strict CSP with hash for the one inline script, X-Frame-Options, no third-party scripts | — |
| **D** Resource exhaustion | upload, API | request size limits, drained bodies, bounded memory in rate-limit tables, chunked long analysis | One process; a flood from an allowed address can still slow readers (no global rate limit); load test numbers in the runbook |
| **D** Ransomware / disk full | host | backups, restore drill, non-root, read-only root | Offline/immutable backups are the hospital's |
| **E** Privilege escalation | roles | per-route checks; admin cannot alter reviews; erase/export admin-only | Admin is powerful (users, thresholds, erase): consider two-person approval for erase ([OWNER]) |
| **E** Container escape | deployment | non-root, read-only, no extra capabilities (compose) | Host hardening is the hospital's |
| Supply chain | build | hashed Python lock file, pinned base images by digest, `npm ci`, pip-audit/npm audit/SBOM in CI, no network at run time | CI never run on a hosted runner yet; releases unsigned; no provenance attestation |
| Update channel | releases | image moved by hand (`docker save/load`) | Define how the hospital verifies an image came from the vendor (signature/checksum) |

## Security objectives to confirm with the hospital
Confidentiality of patient data, integrity of signed reports and audit, availability during clinic hours, accountability of every action. **[OWNER]** Decide the patch SLA, vulnerability-disclosure contact, and incident-response responsibilities in the customer contract.
