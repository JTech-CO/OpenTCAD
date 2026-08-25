# M2 native-object runtime fencing conformance

[한국어](../../ko/m2/native-runtime-fence-conformance.md) | [M2 status](README.md)

- Status: engine-independent candidate contract tested, product disabled
- Reference runtime: strict in-memory mock only
- Product Docker and Podman adapters: not implemented

## Contract boundary

`RuntimeFenceAuthority` is the adapter-independent authority consulted around every job-bound runtime operation. The supplied `InMemoryRuntimeFenceAuthority` is a shared, process-local reference implementation for conformance testing. It records the highest activated owner generation for each canonical job UUID. A lower token, an unactivated token, or the same token paired with another owner fails with stable `operation-fenced`.

Each bound call activates its `RuntimeFencingContext` immediately before entering the adapter operation and verifies the same context immediately after the operation returns. The second check suppresses a stale success result when a newer owner activates while an earlier native request is in flight.

This authority is not durable across processes. Durable store commit and runtime activation are not one atomic action.

## Managed-object metadata

Every managed volume and container created through the bound mock adapter stores these exact metadata labels:

| Label | Required value |
|---|---|
| `tcad.job_id` | Canonical job UUID |
| `tcad.owner_id` | Canonical owner UUID |
| `tcad.fencing_token` | Canonical positive decimal integer |

`RuntimeFencingContext.from_labels()` reconstructs the observed generation and fails closed on a missing label, non-text value, noncanonical UUID, leading zero, or nonpositive token. Other unrelated runtime labels may coexist. `RuntimeJobBackend.inspect_fence()` exposes only the normalized fencing context for a job-bound managed handle.

## Object authorization rules

Normal lifecycle work requires the requested generation to match the object's stored generation exactly. This covers input staging, container creation, start, wait, and artifact collection. A current higher generation may access a predecessor object only for `query`, `kill`, or `cleanup`, which lets cancellation and recovery converge existing objects without continuing the predecessor's execution. Same-token owner ambiguity, a higher observed token, and every cross-job use fail closed.

The adapter checks object labels on every operation, not only at creation. The authority check and object-label check are separate requirements: the first establishes the current requester; the second establishes which generation owns the native object.

## Reusable evidence

`RuntimeFenceConformanceMixin` defines five unchanged cases for future adapters:

1. exact label persistence and normalized inspection on volumes and containers;
2. fencing across two adapter instances that share one authority;
3. rejection of the same token paired with another owner;
4. predecessor access limited to query, kill, and cleanup during takeover;
5. rejection of cross-job object inspection and mutation.

Three focused tests additionally reject malformed labels and verification before activation, and place a deterministic takeover after an earlier mock wait has mutated native state but before its result returns. The older caller receives `operation-fenced`; the current owner then removes the predecessor container and volume and rechecks zero managed objects.

This last case proves stale-result suppression and safe cleanup convergence. It does not prove that a submitted native call was revoked or that its mutation was rolled back.

## Product gate

A future Docker or Podman adapter must implement the same authority, label persistence, normalized inspection, per-operation object enforcement, pre-operation activation, and post-operation verification, then pass the common suite unchanged. Product promotion additionally requires an approved immutable engine profile, approved M2 entry documents, native-platform fault evidence, cross-process durable authority design, and explicit in-flight revocation or convergence evidence. This slice opens no runtime socket and grants no product execution authority.
