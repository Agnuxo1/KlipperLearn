# ChatGPT plugin package and optional MCP tools

The portable package is `plugins/printer-optimizer/`. Its root `plugin.json`
identifies a skills-only plugin; it deliberately has no mandatory local server,
API credential, invented registered connection ID or lifecycle hook. The repository
marketplace metadata is `.agents/plugins/marketplace.json`.

The skill contains a dependency-free Python helper and an original STL coupon.
It runs on files selected by the user in an assistant environment that supports
file/code work. Installing a skill in a supported assistant does not install
firmware or a persistent printer service. Public-directory submission, approval,
account installation and a real conversation acceptance test are separate steps.
They have not been performed merely by committing this repository.

## Optional connected tools

For developers who already run a local KlipperLearn host:

```sh
python -m pip install -e '.[mcp]'
python -m klipperlearn.optimizer_mcp
```

The default transport is stdio. `--transport streamable-http` binds only to
`127.0.0.1:8791/mcp`. The MCP module has no private database reader, arbitrary file
path parameter or printer actuation tool. Its five default operations are:

- `optimizer_contract`
- `review_printer_trials`
- `prepare_ai_review`
- `check_ai_proposal`
- `build_slicer_profiles`

They return data; creating profiles does not write files on the server. The host
assistant may subsequently create explicit downloadable artifacts. No OAuth
identity is invented and loopback HTTP must not be made public without proper
access control. A remote public service requires separately implemented and
reviewed authentication, authorization, rate limits and operational monitoring.

An operator can additionally enable the bounded read-only discovery tool by
setting `KLIPPERLEARN_DISCOVERY_NETWORKS` to explicitly authorized RFC1918 CIDRs.
This is disabled by default. Never place credentials in that variable.

The optional SDK dependency is intentionally bounded to the maintained 1.x line,
`mcp>=1.28,<2`. The upstream SDK documents that major version 2 has incompatible
APIs. A future migration should update both protocol tests and server code, not
silently resolve to a new major version.

## Connecting from ChatGPT

Use the current official developer-mode flow. A cloud connection cannot reach
`localhost` or a private home IP directly. For private-host access OpenAI documents
Secure MCP Tunnel. It requires a local tunnel client, separate account/workspace
permissions, tunnel configuration and a runtime API credential. That optional
route therefore does not satisfy a literal zero-install requirement; the skills
and file workflow is the zero-additional-printer-service option.

Do not paste credentials in a conversation or place them in the public plugin.
No tunnel is created or enabled automatically by this package. A public-directory
listing requires its own submission requirements and is not implied by development
mode connectivity. Availability and UI can differ between accounts and surfaces.

Official references checked during implementation:

- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/build/mcp-server
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/modelcontextprotocol/python-sdk

## Test before installing for others

Test original-profile preservation; absent, forged or stale evidence; cancelled
and partial benchmarks; different layers; denied network scope; missing photo
review; duplicate records; incompatible printer presets; and an unavailable MCP
server. Run the included pure tests and protocol smoke test without a printer.
Then perform an explicit real assistant test, followed by a supervised slicer import
and print test. Do not describe source-level tests as proof of physical quality.

## Public submission and free access

A skills-only public submission is supported; no public MCP endpoint is required
for this package. The publisher charges no fee and requires no external account
or model API key. OpenAI plan, tool, regional and workspace limits still apply.
The [submission kit](../submission/README.md) contains the listing, support/policy
URLs and five positive/three negative test procedures. Actual portal access was
blocked by missing developer identity verification before a draft could be created.
Verification, installed-ChatGPT testing, submission, approval and publication remain
separate steps. GitHub availability is not ChatGPT directory availability.
