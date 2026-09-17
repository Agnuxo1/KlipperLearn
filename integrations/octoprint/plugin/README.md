# OctoPrint-KlipperLearnEvidence

A zero-cloud, read-only OctoPrint companion for creating small local evidence
manifests that can later be reviewed by KlipperLearn or another tool chosen by
the operator.

The plugin does not modify G-code or printer state. It does not provide automatic
optimization, image analysis or remote control. It records content identity for
new local files and normalized lifecycle evidence for started/completed/failed/
cancelled prints.

See the parent [integration guide](https://github.com/Agnuxo1/KlipperLearn/tree/main/integrations/octoprint) for scope, current validation and
OctoPrint policy notes.

## Version 0.1.1 safety review

Hashing is bounded to 512 MiB and rejects links or changes during a read. Event
metrics reject booleans, infinities and impossible percentages; free-text failure
messages are not copied into evidence. Only safe relative file names are retained
for local correlation; these can still identify a user project and must be reviewed
before external sharing. Errors are logged by class, not with private paths.
Restarted workers use a fresh queue and ignore events after shutdown.
The plugin remains independent and unregistered; native OctoPrint installation
and physical-printer operation have not been validated.
