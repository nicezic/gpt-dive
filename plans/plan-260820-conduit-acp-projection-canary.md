# Conduit ACP Projection Canary

## Problem Statement

The conversation-plane canary proved that one complete Web SOL answer can be mirrored through `@c emit` into Redis/NDJSON, but that event is not yet sufficient to act as an ACP agent session. ACP requires explicit session identity, user prompt input, session updates, cancellation, and turn-completion semantics. Promoting the current Redis event envelope directly into the Conduit domain would mix conversation semantics with transport metadata and automatic task snapshots.

## Solution

Run a disposable ACP v1 projection canary against the observed Conduit conversation event. Treat ACP schema v1.20.0 as the stable compatibility target and use v2 only as a forward-compatibility check because v2 remains alpha. The canary should determine whether the current Conduit conversation information can map losslessly onto the minimum ACP lifecycle: initialize, session/new, session/prompt, session/update, prompt completion, and session/cancel.

Reuse the already-proven asymmetric Web SOL transport when reasoning about the later full loop: Edge/Playwright is input-only to ChatGPT Web, and explicit Conduit emission is the output path. Do not build a second browser transport.

## User Stories

1. As the user, I want Conduit to expose Web SOL through ACP without making ACP the canonical Conduit domain, so that other clients can be added later without protocol lock-in.
2. As an ACP client, I want a stable session identity, so that prompts and updates can be correlated without test-only turn markers.
3. As an ACP client, I want to send user prompt content into a session, so that VS Code can initiate a real Web SOL turn.
4. As an ACP client, I want assistant output represented as ACP session updates, so that existing ACP clients can render Web SOL responses.
5. As an ACP client, I want an explicit turn-completion signal and stop reason, so that I do not infer completion from DOM state or Redis timing.
6. As an ACP client, I want cancellation to map to a real conversation/work cancellation boundary when supported, so that cancellation is not merely cosmetic.
7. As a maintainer, I want Redis IDs, timestamps, and automatic task snapshots to remain transport/task-awareness metadata unless an ACP requirement proves they belong to conversation semantics.
8. As a maintainer, I want the first ACP probe to be disposable and schema-focused, so that a failed mapping does not force production abstractions.
9. As a maintainer, I want the existing Council-proven Edge/Playwright input path reused for a later full E2E, so that Conduit does not create another browser automation transport.
10. As the user, I want the first implementation target to be stable ACP v1, while keeping the Conduit domain neutral enough to project to v2 later.

## Implementation Decisions

- Target stable ACP v1 schema behavior first. Treat current ACP v2 behavior as a compatibility constraint, not the implementation contract.
- Keep three conceptual layers separate: Conduit conversation domain, ACP protocol projection, and NDJSON/Redis transport.
- The projection canary uses the observed complete assistant text event as evidence, not as a frozen canonical schema.
- Session identity must become an explicit conversation correlation concept before a real multi-session ACP bridge is possible. A test nonce or Turn Marker is not an acceptable production substitute.
- User prompt content and assistant content are distinct conversation directions and must not be collapsed into the existing output-only `emit` meaning.
- Turn completion must be explicit. For ACP v1, the prompt response stop reason is the compatibility target; the domain should remain capable of projecting to v2 idle/state-update completion semantics.
- Streaming is not required for the first proof. One complete assistant output may be projected as a single agent message chunk followed by explicit completion, provided the domain does not prevent later chunked updates.
- The existing asynchronous task snapshot is not part of the ACP conversation stream by default. Tool/task projection requires separate evidence.
- The later full Web E2E should reuse the proven Edge/Playwright input-only adapter and explicit Conduit output path.

## Testing Decisions

- First test the highest-value schema seam: whether one observed Conduit conversation turn can be represented as a valid minimal ACP lifecycle without inventing information.
- The canary must report missing source information rather than synthesize fake session IDs, roles, stop reasons, or cancellation state.
- PASS for the projection probe means the exact minimum missing Conduit conversation fields are identified and a deterministic ACP v1 mapping exists once those fields are supplied.
- A later full E2E is a separate acceptance: ACP client prompt -> existing Edge input path -> Web SOL -> Conduit emit -> ACP client update/completion.
- Do not use DOM response scraping or visual streaming-completion detection.
- Verify stable v1 behavior against the current official ACP schema/docs; use v2 only to check that the proposed Conduit domain is not obviously version-locked.

## Out of Scope

- Production ACP daemon or VS Code extension integration.
- Replacing the current Conduit MCP tool surface.
- AHP support.
- New browser automation transport.
- ACP tool-call, filesystem, terminal, permission, plan, or elicitation surfaces beyond what a minimal text conversation needs.
- Multi-client/session persistence policy beyond identifying the required correlation boundary.
- Promoting Redis event metadata or TrackedTasks into the conversation domain without evidence.

## Further Notes

The conversation-plane live canary already proved the output half of the asymmetric bridge. Council previously proved the complementary input-only Edge/Playwright path. The ACP projection canary therefore focuses on protocol semantics rather than transport feasibility.

## Result — PASS

The disposable projection probe ran against the real Redis/NDJSON `emit` event from the conversation-plane canary. The observed complete assistant text maps directly to one ACP v1 `agent_message_chunk`. Because Conduit `emit` is already defined as a complete Mirrored Full Output, successful `emit` also gives a deterministic normal completion mapping to ACP `stopReason=end_turn`; a new stop field is not required for the first normal-turn path.

The legacy canary event cannot be projected directly only because it predates conversation `session_id` correlation. User prompt content/direction, session creation, and active-prompt state belong to the ACP ingress adapter for the first bridge and do not need to be duplicated into the Web SOL output event. Redis ID, transport timestamp, and the automatic task snapshot remain outside conversation-domain semantics without further evidence. Cancellation remains a separate live acceptance rather than a fake/no-op mapping.

The first production slice therefore adds only optional `session_id` correlation to Conduit `emit`; the existing `result.text` and Mirrored Full Output semantics remain unchanged.

A disposable ACP stdio normal-turn canary now passes local `initialize` and `session/new` NDJSON handshakes. The remaining live prompt loop reuses the existing Edge input bridge and correlated Conduit output.
