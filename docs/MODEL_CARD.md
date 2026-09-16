# Model and algorithm card

## Released algorithm

Type: deterministic advisory heuristic, implemented in JavaScript.
Training: none. Parameters: caller-supplied policy, not learned weights.
Inputs: structured, reviewed observations under a declared fixed context.
Outputs: non-executable bounded proposals or an explicit abstention/stop reason.
Validation: synthetic unit and UI tests. No measured hardware accuracy or speed gain.

## Planned phone-local visual model

A small, quantized image/sensor model is a product goal, not a released capability.
There are no trained weights or claimed CNN accuracy in this repository. Random
weights and smoke tests must never be presented as a validated model.

Before release, document architecture, weight hash, license, training data consent,
label rubric, preprocessing, sensor alignment, phone resource use and provenance.
Split validation by printer, session, material and camera/mount configuration to
avoid adjacent-frame leakage. Publish confidence calibration, abstention behavior,
false positives and missed defects. Evaluate sensor ablations and drift separately.
A model that sees frame vibration alone must not claim exact step-loss reconstruction.

## External model mode

This release supplies a manual evidence exchange protocol, not a connected API
client. The user chooses what to share and with whom. Model output is untrusted;
unsupported evidence, stale references, unknown fields and out-of-range values
are rejected. Passing that gate still does not authorize a print.

ChatGPT subscriptions and API usage have separate billing; the manual workflow
requires no API key and does not claim to bypass any product quota.
Source: [OpenAI billing guidance](https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api).
