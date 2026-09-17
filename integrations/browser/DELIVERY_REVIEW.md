# Chrome extension delivery review — 17 September 2026

**Artifact:** KlipperLearn Slicer Review 0.1.0, Manifest V3.
**Publisher:** Francisco Angulo de Lafuente.
**Price:** free; no publisher account or separate model API key.
**License:** GPL-3.0-or-later, preserved in the extension package.

## Completed

The browser implementation contains session import and guided entry, original-photo
preview and byte hashes, human-reviewed trial entry, comparable-configuration
selection, Quality/Standard/Speed paired Orca exports, a manual AI request/reply
workflow, bounded unvalidated-trial exports and original calibration STL download.
No reported print result, native slicer import or new physical trial was fabricated.

All executable code is bundled. The manifest requests no privileged/host
permissions. No content scripts, tracker, persistent data store, remote-code
loader, automatic inference, LAN scan or printer command exists in this extension.
Its background worker only opens its packaged workspace after a toolbar click.

The English store kit contains the description, single-purpose declaration,
privacy disclosures, review instructions, original project icon, three 1280 x 800
screenshots and a 440 x 280 promotional tile. The screenshots show the actual UI
running with synthetic data in the documented DOM harness, not a store install.
An extension-specific privacy-policy HTML page is ready to host but is not public.

## Validation recorded in this delivery

1. **70 Node tests passed.** Thirty are differential cases against the byte-verified
   original Python optimizer, comparing session/configuration IDs, exclusions,
   mode selections, numeric formatting and paired accepted/experimental presets.
2. **16 Chromium DOM-harness checks passed.** Guided session/trial entry, generated
   ZIPs, proposal validation, invalid-input recovery, photo hashes, small-screen
   layout, help/privacy and zero external requests were exercised.
3. **14 extension files passed static package checks:** MV3 configuration, local
   references, JavaScript module syntax, icons, bounded resources, licenses,
   forbidden network-code patterns and selected credential patterns.
4. Output ZIPs are readable with valid CRCs, and their contents match their source.
   Build outputs are deterministic and accompanied by SHA-256 digests.

The browser harness retains the sandbox's browser policies. It renders only
self-authored content in a blank document; the secure-origin hash API is replaced
with a Python hashlib-backed test double, and download Blobs are captured rather
than navigated. This does not test actual native extension/module installation,
Chrome permission enforcement or native browser downloads. A separate optional
native smoke-test program is supplied for an authorized test environment. Do not
alter enterprise policies to bypass an installation restriction.

## Still not performed

- Native installation acceptance in the publisher's Chrome profile.
- Import/slicing acceptance in an actual OrcaSlicer installation.
- Physical printing or independent image-quality validation.
- Hosting and verification of the extension-specific public privacy-policy URL.
- Upload to Chrome Web Store, store-item creation, submission, approval or publication.
- Import/commit of these new Chrome files into the GitHub repository.

## Why publication did not happen

The connected PC was available, but the exposed remote connector functions were
read-only; no process execution, browser manipulation or file writes were offered.
GitHub's available functions were also read-only. Broad user authorization does
not itself add those missing operations. No read endpoint was misused to trigger a
write and no credentials, sessions or access controls were bypassed.

The extension and source/store ZIPs are delivered as conversation files. They are
not claimed to exist on the user's Windows disk, in GitHub or in Chrome Web Store.
No payment, new developer registration, EnigmAgent change, live Linux update or
printer action occurred.

## Source provenance and measurement attribution

The Python reference is identical to the published optimizer in project commit
9e92d1e6173a87406dbeb2cfbe4e26d0ada2430f (Git blob SHA-1
6386f0f1eec53f276aec213234888c12c37d1096). Numeric token spellings are retained so
Python-exported identities survive round trips. Noncanonical manual respelling
can invalidate identities; the code never rewrites historical hashes to hide it.

Flashforge Creator Pro Benchys belong to operator-plus-ChatGPT tuning, not local
KlipperLearn. Anycubic 4Max Pro charts and cubes belong to the separate KlipperLearn,
phone and webcam setup. Neither is a physical validation of this Chrome extension.
