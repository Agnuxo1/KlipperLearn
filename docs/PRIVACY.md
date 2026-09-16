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

## Printer Optimizer plugin and MCP

The portable skill runs inside the selected assistant. Files the user attaches to
that assistant are shared with that provider under its policies; file-first does
not mean cloud-private when a cloud assistant is selected. The helper itself has
no network code, trackers or inference call. Its input filter rejects common
credential fields, but cannot guarantee detection of every secret format.

The optional MCP server receives only explicit structured arguments. It cannot
read arbitrary local paths or private printer stores. A caller can receive all
returned preset data, including preserved custom G-code from supplied bases.
The numerical advisor request deliberately omits those base scripts. Review
original profiles locally before sharing them. No secrets are bundled or needed
for the five default tools. Do not expose an unauthenticated MCP HTTP listener.

Optional subnet discovery is performed by an approved local host, not OpenAI
servers directly. Results include LAN addresses and API identification, which
may be visible to the connected assistant. It requires explicit user consent
and a server-side allowlist; no Wi-Fi passwords or private histories are read.
