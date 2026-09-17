# OctoPrint integration: local evidence manifests

This integration is a separately maintained OctoPrint plugin. It listens to a
small set of OctoPrint file and print lifecycle events, then writes local JSON
manifests for later KlipperLearn review. It never sends G-code, changes a heater,
moves an axis, starts a print, scans the LAN or contacts a cloud service.

## Why this is external

OctoPrint's current contribution policy explicitly rejects pull requests that are
fully or predominantly AI-generated, and its `AGENTS.md` instructs AI agents not
to write code for contributors. This implementation therefore stays in the
KlipperLearn repository and is **not** proposed to `OctoPrint/OctoPrint`.

The official plugin repository has a separate registration process and explicitly
supports an `ai-developed` attribute, but requires active maintainer responsibility
and an understanding of the plugin independent of generative AI availability.
Registration is not attempted in this round.

## Current OctoPrint contracts used

Checked on 17 September 2026 against current OctoPrint documentation/source:

- `EventHandlerPlugin.on_event()` runs on OctoPrint's consecutive event queue, so
  this plugin only enqueues a bounded background task and returns immediately.
- `FileAdded` provides storage and storage-relative path.
- `PrintStarted`, `PrintDone`, `PrintFailed` and `PrintCancelled` provide lifecycle
  data. User/owner identifiers and printer network details are deliberately omitted.
- `FileManager.path_on_disk(storage, path)` resolves an OctoPrint-managed local
  file for hashing. Non-local storage is ignored.
- Modern OctoPrint plugins are discoverable through the `octoprint.plugin`
  `pyproject.toml` entry-point group.

## Install in a disposable OctoPrint environment

The plugin is packaged under [`plugin/`](plugin/). From a clone of KlipperLearn,
install it in the same Python environment as OctoPrint:

```bash
python -m pip install ./integrations/octoprint/plugin
```

Restart only that disposable OctoPrint development instance after installation.
This project has not installed the plugin into a production printer host.

## Evidence written

File manifests contain a SHA-256, byte count and OctoPrint storage-relative path.
Print manifests contain only lifecycle state and documented timing/reason/progress
fields when present. No G-code body, absolute host path, user identity, IP address,
API key or printer control command is stored.

Manifests are created with exclusive filenames and restrictive permissions where
the operating system supports them. Existing evidence is not overwritten. A
single bounded daemon worker prevents expensive hashing from blocking OctoPrint's
event queue; shutdown cancels in-progress hashing between chunks.

## Validation boundary

Unit tests use a minimal fake OctoPrint plugin/event surface and real temporary
files. They validate no file mutation, privacy filtering, background queueing,
non-local exclusion and package metadata. A real OctoPrint GUI/plugin-manager
installation and repository-directory registration remain unverified.
