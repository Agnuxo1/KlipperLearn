# Source review: KlipperLearn 0.5.1

## Baseline, scope and provenance

This release imports the original 0.5.0 Python application and browser companion.
It preserves their GPL-3.0-or-later notice and the separately scoped MIT material
from the earlier reference-only publication. All work took place in an isolated
copy; the original 140 selected files retained their hashes. No printer motion,
heating, printing, firmware changes or service restarts occurred during review.

The review combined source inspection, static analysis, full regression tests,
real browser execution with simulated hardware, package builds, dependency audit,
and a publication-specific private-data scan. It is not an independent security
certification or proof that all possible defects have been eliminated.

## Corrected issues

1. **Camera freshness:** stale disk caches and stopped streams could remain visible.
   Snapshots now require an active frame no older than five seconds; stopping a
   stream clears it. Streaming waits for genuinely new frames and does not replay
   old observations as live evidence.
2. **Private routes and authentication:** session records require the configured
   token; duplicate authentication headers fail closed. Token comparison handles
   malformed Unicode without leaking credentials. Private responses are no-store.
3. **Bounded requests:** streaming limits apply before buffers grow. Invalid lengths,
   duplicate JSON keys, non-finite values, malformed Unicode and excessive nesting
   are rejected. Tests confirm rejected controls never reach Moonraker.
4. **Configuration and networking:** numeric settings reject booleans, infinities
   and overflow. Loopback detection parses addresses rather than accepting a hostname
   prefix. Read-only HTTP validates URLs, rejects credentials/redirects, ignores
   environment proxies and bounds response sizes. Forwarded proxy headers are not
   trusted by default.
5. **Model robustness:** invalid versions, shapes, scales, digests, coefficients or
   out-of-distribution features cause abstention rather than a manufactured score.
6. **Optional checkpoint loading:** require a stable PyTorch version >= 2.10.0 and
   bounded regular checkpoint files, with no unsafe-loading fallback. Only trusted
   model sources are permitted; metadata checks do not make arbitrary files safe.
   Upstream advisory: https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p
7. **Storage and operational clarity:** SQLite read-only file URIs are escaped;
   fixed SQL operations replace unnecessary string construction. Token files can
   be created exclusively without displaying their contents or overwriting an
   existing credential. Windows file protection also depends on directory ACLs.
8. **Portability and publication:** remove personal workstation dependencies,
   translate the public interface and application messages to English, keep original
   tests while updating translated expectations, package both browser asset
   directories, and add repeatable test runners and Linux CI.

## Validation outcome

The reviewed application passed **275 tests plus 185 subtests**, compared with the
original 215 plus 185. The exporter passed 25 tests; all 10 JavaScript application
programs and all 47 separate reference-core tests passed. Ruff E9/F reported no
findings. The runtime dependency audit covered 19 installed packages and reported
no known vulnerabilities at review time. Two Bandit findings were reviewed as
non-exploitable uses: rejecting a wildcard listener and escaping XML text. Two
third-party deprecation warnings remain documented in [validation](VALIDATION.md).

## Public/private boundary

Original runtime databases, old Git history, model weights, credentials, private
certificates, local deployment logs and historical operational journals were not
published. Public configuration uses generic addresses. Approved project images
are stored in the repository without source metadata; conceptual/retouched images
are labelled separately from the source workshop photograph.

Source scan results are checks with a stated scope, not a guarantee that every
possible secret format is discoverable. No original credential was deleted or
rotated and no private working configuration was overwritten.

## Deliberately unresolved product milestones

Native phone-only Klipper hosting over USB, a turnkey Android installer, trained
and independently evaluated visual weights, automatic cloud-model integration,
physical bed clearing, and unattended recursive tuning remain distinct milestones.
The source contains useful bounded experimental workflows but does not establish
those capabilities by passing software tests. The release has not been merged
into or endorsed by Klipper, Moonraker, Mainsail, OrcaSlicer or Voron.
