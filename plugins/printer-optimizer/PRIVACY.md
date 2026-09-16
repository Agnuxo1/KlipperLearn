# Printer Optimizer privacy notice

Publisher: Francisco Angulo de Lafuente. Applies to the skills-only
KlipperLearn Printer Optimizer 0.6.0 package prepared for ChatGPT.

## Data used

The assistant uses files and information the user chooses to provide: printer
identity, relevant material/nozzle settings, sanitized slicer presets, original
calibration photographs, logs, and reviewed trial records. It creates proposed
settings, reports and preset files in that assistant's file environment.

The skills-only package has no publisher-operated backend, telemetry endpoint,
analytics, advertising, account registration, payment flow or model API call.
Its bundled Python helper does not connect to the network. The publisher does
not receive files through the helper and does not store them on a project server.

Files submitted to ChatGPT are processed by OpenAI under the user's applicable
ChatGPT settings, terms and privacy controls. Installing this skill does not make
cloud conversations offline or exempt them from the platform's data policies.
The host assistant may use separately available tools under its own permissions;
those tools and optional connections retain their providers' policies.

## Protection and sharing

Do not provide passwords, API keys, Wi-Fi credentials, private certificates,
personal documents or unrestricted printer configuration dumps. Remove unrelated
people and identifying details from calibration photographs before sharing them.
Do not generatively modify the printed part as evidence. Keep originals locally.
The helper checks common credential fields; that is not a guarantee that every
possible secret format can be detected. Nothing is uploaded to GitHub automatically.

## Retention and requests

The package does not maintain a publisher-side user database. Manage uploaded
files and conversation retention with the host platform's controls. Local users
manage copies they save. The publisher cannot delete files held by another
platform. The publisher's separate KlipperLearn self-hosted server and optional
MCP deployment are not required by this skills-only package and require their
own explicit setup and operator-controlled retention.

Support: https://github.com/Agnuxo1/KlipperLearn/issues
For privacy questions, open a minimal issue without personal data and ask for an
appropriate private communication channel. Do not publish private evidence or
credentials in an issue. This notice must be updated before adding any publisher
backend, account, collection, retention or payment functionality.
