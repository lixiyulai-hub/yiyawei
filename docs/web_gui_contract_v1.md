# Web GUI Contract v1

This document defines the versioned state, transition, polling, editing, and
confirm rules for the local web GUI. It is a controller-independent contract.
The existing unversioned endpoints remain in place during migration; this
contract does not add `/api/v1` routes.

## State phases and events

The only phases are `warming`, `ready`, `recording`, `processing`, `done`, and
`error`.

| Current phase | Event | Next phase |
| --- | --- | --- |
| `warming` | `WARMUP_SUCCEEDED` | `ready` |
| `warming` | `WARMUP_FAILED` | `error` |
| `ready`, `done`, or `error` | `START_REQUESTED` | `recording` |
| `recording` | `STOP_REQUESTED` | `processing` |
| `recording` | `RECORDING_FAILED` | `error` |
| `processing` | `PROCESS_SUCCEEDED` | `done` |
| `processing` | `PROCESS_FAILED` | `error` |
| `error` | `RETRY_REQUESTED` | `ready` |

`STATE_REFRESHED` and `SETTINGS_UPDATED` are legal same-phase events in every
phase. In `done`, `EDIT_STARTED`, `EDIT_RESTORED`, `CONFIRM_SUCCEEDED`,
`CONFIRM_FAILED`, `PASTE_SUCCEEDED`, and `PASTE_FAILED` are also legal
same-phase events. Every other transition is invalid. A refresh cannot be used
as a general-purpose phase change.

## State payload

All v1 state fields are required. Extra fields may be ignored by a reader, but
declared fields must have the types below.

| Field | Type and rule |
| --- | --- |
| `schemaVersion` | integer, exactly `1` |
| `operationId` | non-empty string |
| `revision` | integer greater than or equal to zero |
| `phase` | one of the six phases above |
| `status`, `target` | string |
| `rawText`, `finalText` | string |
| `mode`, `outputScript` | string |
| `useFast` | boolean |
| `asrModel`, `asrDevice`, `llmModel` | string |
| `asrMs`, `llmMs`, `recordId`, `riskLevel` | string |
| `elapsedSec`, `level` | finite number |
| `pasted` | boolean |
| `lastError` | string |
| `updatedAt` | finite number; diagnostic only |

The current payload without `schemaVersion` is legacy v0. A contract consumer
must opt in with `allow_legacy=True`; absence of a version is not silently
treated as v1. Legacy validation still requires and type-checks every existing
field from `WebGuiState.to_dict()`. Any declared schema version other than `1`
is rejected, including when legacy compatibility is enabled.

## Ordering and polling

`revision` is the global monotonic ordering key. `updatedAt` never decides
whether a snapshot is newer.

| Incoming condition | Result |
| --- | --- |
| revision lower than current | reject as stale |
| same revision and same operation ID | accept idempotently |
| same revision and different operation ID | reject as conflict |
| higher revision | accept |

For the same operation, an accepted poll replaces non-text state such as phase,
status, and metrics. A locally dirty `rawText` or `finalText` is retained, and
its original edit base is retained for optimistic confirmation. A higher
revision carrying a new operation ID replaces the whole snapshot and resets
both dirty flags. The rules are represented by immutable data and pure merge
functions rather than DOM state.

## Confirm payload and conflict boundary

Every v1 confirm request requires these fields:

| Field | Type and rule |
| --- | --- |
| `schemaVersion` | integer, exactly `1` |
| `operationId` | non-empty string |
| `baseRevision` | integer greater than or equal to zero |
| `scope` | `raw` or `final` |
| `rawText`, `finalText` | string |
| `baseRawText`, `baseFinalText` | string |

Before any edit persistence or paste, the receiver compares `operationId`,
`baseRevision`, `baseRawText`, and `baseFinalText` with current authoritative
state. Any mismatch is a conflict. Conflict detection is side-effect free; a
conflict must not save an edit and must not paste text.

## Required flow sequences

1. Startup: `warming -> ready`; warm-up failure is `warming -> error`, and an
   explicit retry is `error -> ready`.
2. Manual recording: `ready -> recording -> processing -> done`. Recording or
   processing failures end in `error` through their named failure events.
3. Auto-stop exactly once: it follows the same
   `ready -> recording -> processing -> done` path. A second `STOP_REQUESTED`
   in `processing` is invalid, preventing a second state-path stop.
4. Dirty edit and polling: `done -> done` for `EDIT_STARTED` and
   `STATE_REFRESHED`. Same-operation polls update non-text fields but preserve
   dirty text. A new accepted operation replaces text bases and clears dirty.
5. Restore, confirm, and stale base: `EDIT_RESTORED`, successful confirm, and
   failed confirm all remain in `done`. Matching operation, revision, and both
   base texts may confirm. Any stale operation, revision, or base text produces
   a conflict before paste/edit side effects.
