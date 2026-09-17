# Moonraker integration

The implementation lives in `../../tools/exporter/export_workspace.py` so the
same reviewed GET-only client is used for history and source handoff. There is no
duplicate HTTP client and no Moonraker component to install.

See `../../docs/INTEGRATIONS.md` for behavior, authorization limitations and scope.
Mainsail's `/history` page is a UI; the reader uses `/server/history/list` directly.

## Offline history review

The [strict history normalizer](HISTORY_REVIEW.md) complements the existing GET-only
collector. It keeps statuses, print/total time and machine/workflow identity separate
without fetching additional data or treating job completion as quality evidence.
