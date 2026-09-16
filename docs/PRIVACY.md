# Privacy and data handling

The application stores experiment records, human reviews, photographs and sensor
features on the configured local host. The phone uses browser storage for pairing,
preferences and its durable sensor outbox. Raw audio is not saved by the aggregate
collector; camera images can still reveal people, surroundings or identifying data.

Authentication tokens belong in private files and headers, never in public logs,
issues or source. Pairing links use a URL fragment removed after processing; the
paired token can remain in local browser storage. Use a dedicated trusted device
and clear site data when removing access. No token is a substitute for trusted
HTTPS, a firewall and a limited network exposure policy.

Private session/API responses use `Cache-Control: no-store`. The service worker
must not cache authenticated API data. A stale camera cache is not served as live.
A camera snapshot expiring does not delete previously authorized evidence images.

Exported evidence archives may contain sensitive local records. Review them before
sharing. The publication exporter is a review aid, not an automatic guarantee that
every possible secret format has been removed. Runtime `data`, `work`, credentials,
private certificates, old Git history and operational journals are excluded from
the source publication. Public artwork is author-approved and metadata-stripped.

The external-advisor reference exports a local request for manual review. This
release does not automatically upload data to ChatGPT or another cloud service.
Sharing evidence with a third party remains an explicit user decision. No account
credential, cloud API key, analytics tracker or external font is bundled in the UI.
