# OctoPrint Plugin Repository registration checklist

This is a readiness checklist, **not** a submitted repository entry.

Current official guidance checked on 17 September 2026 requires a plugin author to
be willing and able to maintain the plugin, understand its implementation without
depending on generative AI, avoid hidden system changes, and disclose AI-assisted
development with the `ai-developed` attribute. The KlipperLearn plugin has no cloud
backend, no external account and no installation-time system modification.

Before any registration PR to `OctoPrint/plugins.octoprint.org`:

1. Install the wheel in a disposable current OctoPrint instance and verify startup,
   shutdown, `FileAdded` hashing and print lifecycle manifests through the real UI.
2. Confirm the operator accepts ongoing plugin-maintainer responsibility independent
   of AI availability and can explain/debug the implementation.
3. Publish a stable standalone installation archive or dedicated plugin repository;
   the current monorepo subdirectory is not presented as an official archive URL.
4. Create the repository entry with `attributes: [ai-developed]`, GPL-3.0-or-later,
   Python compatibility and only compatibility versions actually tested.
5. Re-read registration rules immediately before submission and search for duplicates.
6. Submit at most one focused registration PR with explicit AI-development disclosure.

No registration PR, core issue or core PR is authorized automatically while items
1-3 remain unresolved. OctoPrint core's separate AI policy prohibits this AI-authored
implementation from being submitted there as a core contribution.
