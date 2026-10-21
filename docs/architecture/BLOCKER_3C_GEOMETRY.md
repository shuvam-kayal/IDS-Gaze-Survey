# Blocker 3C — Durable study-scoped geometry

Status: durable GeometrySnapshot v2 foundation implemented; production trusted
context construction remains Blocker 3D.

## Scope and trust boundary

`contracts/schemas/geometry-snapshot.v2.schema.json` already contains the
necessary study-scoped identity and viewport/rectangle fields. P3 now stores
validated v2 snapshots in PostgreSQL through
`TelemetryRepository.persist_geometry_snapshot()`.

The repository requires a `GeometryScope(session_id, study_id,
aoi_set_version)` supplied by an upstream server-owned session/assignment
resolver. It checks that all three values in the snapshot match that scope.
This check prevents accidental cross-study writes, but persistence alone does
not authorize browser data. The internal `provenance` column records the source
as `browser_submitted_untrusted` by default; the rectangles must still be
treated as untrusted until the future trusted context provider applies the
approved session, configuration and lifecycle checks.

## Identity and retries

The durable snapshot identity is the composite key:

```text
(session_id, study_id, snapshot_id)
```

The same snapshot identity with identical canonical v2 content is an exact
retry and is a no-op. Reuse with different geometry or viewport content raises
the existing P3 `RecordIdentityConflict`. The same `snapshot_id` may therefore
appear in different sessions or studies without collision, while a scope
cannot contain two competing versions of one snapshot identity.

The server stores `ingested_at` separately from the contract's client-captured
`captured_at`. It never replaces the occurrence/capture timestamp with arrival
time.

## Validation and resolution

Only v2 snapshots are durably accepted because v1 has no `study_id`. Validation
requires UTC `captured_at`, finite positive viewport dimensions and zoom,
non-negative scroll offsets, unique AOI IDs, finite rectangle coordinates,
integer priorities, and strictly positive rectangle extents. Invalid data is
rejected before opening the write transaction.

`resolve_geometry_snapshot()` requires an explicit session, study, AOI-set
version, and timestamp. It returns the latest snapshot in that exact scope
whose `captured_at` is at or before the requested time, ordered by
`captured_at ASC, snapshot_id ASC`. A snapshot captured after the observation
time is stale for that observation and is not selected. No “latest across
studies” fallback exists, and no snapshot means unresolved geometry rather
than a guessed AOI.

Session deletion removes all geometry rows for that session. Expiration
cleanup removes geometry with the related expired session processing state.

## Remaining Blocker 3D work

The production `TrustedGazeContextProvider` is still unset and the gaze API
remains fail-closed. Blocker 3D must obtain verified participant-session
state, pinned P2 assignment/configuration, the Blocker 3B lifecycle window,
and a study-scoped geometry snapshot before constructing
`AuthorizedGazeContext`. It must not treat a browser-provided snapshot as
authorization or change the frozen contracts.
