# Optional MCP connection

The default plugin is skills-only and has no server dependency. For an existing
KlipperLearn Python installation, the optional `mcp` extra provides the official
SDK integration:

```sh
python -m klipperlearn.optimizer_mcp
```

A stdio-capable client can use that command directly. `--transport streamable-http`
serves `127.0.0.1:8791/mcp` only. Do not expose it publicly. The source package
has no embedded registered app ID, credentials, live printer data or public URL.
See [ChatGPT setup](../../docs/CHATGPT_PLUGIN.md) for the separate private-tunnel
and account-approval requirements. No inference model is instantiated by the server.
