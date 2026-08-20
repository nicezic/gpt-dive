# Conduit Conversation-Plane Live Canary

## Problem Statement

Conduit already has a Redis fan-out path and an NDJSON consumer, but the conversation plane has not yet proven that one real ChatGPT Web turn can preserve the same complete assistant answer in both places: the native ChatGPT Web final and the Conduit event path. Until that is observed live, expanding the domain model or adding ACP-specific semantics would be premature.

## Solution

Run one live Mirrored Full Output canary through the existing Web-facing `@c emit` seam. The assistant will send the same complete answer through Conduit and return it unchanged as the native ChatGPT Web final, with the current Turn Marker as its final line. Verify the marker-bearing Conduit copy reaches Redis and the NDJSON consumer. Record only the observed conversation-plane behavior and any domain-content pressure exposed by the canary.

## User Stories

1. As the user, I want one real Web turn mirrored through Conduit and ChatGPT Web, so that the conversation plane is proven with live behavior rather than inferred from unit tests.
2. As the user, I want the two copies to contain the same complete assistant answer, so that a future myWeb client can receive the useful output without sacrificing native ChatGPT history.
3. As Web SOL, I want an explicit Turn Marker on the mirrored output, so that the native and Conduit copies can be correlated without inventing a larger conversation schema.
4. As the user, I want the Conduit copy to reach the existing Redis and NDJSON path, so that the current fan-out infrastructure is exercised end to end.
5. As a maintainer, I want the canary to use the existing `emit` seam, so that no new protocol surface is introduced merely for testing.
6. As a maintainer, I want observed content pressure recorded after the canary, so that later domain fields come from real use rather than speculative design.
7. As the user, I want ACP work deferred during this canary, so that the test answers the narrower conversation-plane question first.
8. As the user, I want failures to remain explicit, so that a transport or correlation failure is not hidden behind a fallback path.

## Implementation Decisions

- Use the existing Web-facing Conduit `emit` action as the single live test seam.
- Treat the Mirrored Full Output as the complete assistant answer, not a summary or reduced event.
- Append the current Turn Marker as the final line of that output and use it only for correlation.
- Redis remains the event/fan-out transport and does not become the owner of conversation-domain semantics.
- The NDJSON consumer remains an observation surface; this canary does not promote the current event envelope into the final canonical domain schema.
- Do not redesign `Task`, `TrackedTask`, or introduce ACP mappings as part of this test.
- Record the live result and concrete content/schema pressure after observation.

## Testing Decisions

- The highest-value seam is one real ChatGPT Web turn invoking `@c emit` and then returning the same text natively.
- PASS requires the marker-bearing Conduit copy to be found in the Redis/NDJSON event path and the native final to be identical to the emitted text.
- Correlation uses the Turn Marker already defined by Conduit language rather than adding a new canary-only identifier.
- Existing Redis/NDJSON unit tests remain prior art; this run adds live end-to-end evidence rather than duplicating helper-level tests.
- Record transport success separately from any future judgment about the canonical conversation-domain schema.

## Out of Scope

- ACP server or adapter implementation.
- ACP session semantics or protocol mapping.
- Automatic ingestion of the full ChatGPT conversation context.
- New `Task` or `TrackedTask` schema design.
- myWeb UI implementation.
- GBrain ingestion.
- Alternate event transports or fallback paths.

## Further Notes

This canary follows the accepted Conduit language: Mirrored Full Output, Turn Marker, Redis as fan-out transport, and protocol evolution from observed workflow pressure. If the live turn succeeds, the next useful design question is what minimum conversation-domain content must be preserved for future clients, including whether ACP can be projected losslessly from that domain without making ACP itself canonical.

## Live Result — PASS

On 2026-08-20, one real ChatGPT Web turn sent a Mirrored Full Output through live `@c emit`. The call returned `emitted: true`; the Redis/NDJSON consumer then recorded the same full text under `action: "emit"` with Redis ID `1787235113300-0`, including `Turn Marker: 7` as the final line. The native final for the turn is intentionally held to the same emitted text.

Observed pressure is narrower than the current event envelope. The live NDJSON record contains transport/event metadata plus `result.text` and the automatic `tasks` snapshot. This proves fan-out and correlation, but does not establish that the whole envelope is canonical conversation domain. For ACP work, conversation content and task-awareness should be evaluated as separate semantics before any mapping is accepted.
