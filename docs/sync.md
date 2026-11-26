# Cloud sync contract (web ↔ StudyDeck)

The local web app and the StudyDeck Android app share one Firestore database (provisioned by `infra/`). They don't talk to each other directly. Each signs in with Google through Firebase Auth, so both see the same `uid`, and each reads and writes `users/{uid}/...`. Any client that follows this document can take part.

- Web implementation: `backend/app/cloud/sync.py`, tested in `backend/tests/test_sync.py`.
- Phone implementation: StudyDeck's `MequizmeSyncRepository`.

## Conventions
- Times are Firestore **timestamps**, except fields documented as ISO strings.
- Every doc that other devices pull has a `syncedAt` field, set to the **server** time (`FieldValue.serverTimestamp()` / REST `REQUEST_TIME` transform). Pull with `where syncedAt > cursor orderBy syncedAt`, then set the cursor to the largest `syncedAt` you received. Each collection keeps its own cursor.
- `device` is `"web"` or `"android"`. It's for information only.
- Fields holding JSON are **strings** (`body`, `state`). This avoids Firestore's limits on nested arrays and keeps the documents identical to the local copies.

## Collections

### `packs/{packId}`: written by web, read-only on the phone
| field | type | |
|---|---|---|
| id, name, exam | string | |
| body | string (JSON) | pack document without `items`: taxonomy (exam, topics with weights, passingScore), quizzes, … |
| contentHash | string | |

### `packs/{packId}/items/{itemId}`: written by web, read-only on the phone
| field | type | |
|---|---|---|
| id, packId, type | string | type: `flashcard`, `cloze`, `mcq_single`, `mcq_multi`, `true_false`, `short_answer` |
| position | int | order within the pack |
| topics | array<string> | topic ids |
| body | string (JSON) | the full Study Pack v2 item (`schema/studypack.v2.schema.json`) |
| contentHash | string | |

Only items with status `reviewed` are published. When an item is removed from a pack, the web app deletes its doc.

### `reviews/{uuid}`: both sides; **create-only** (rules forbid update and delete)
| field | type | |
|---|---|---|
| id | string | same as the doc id (UUID v4) |
| itemId | string | |
| rating | int | 1 Again, 2 Hard, 3 Good, 4 Easy |
| source | string | `flashcard` or `quiz` |
| reviewedAt | timestamp | |
| durationMs | int? | |
| device | string | |
| syncedAt | server timestamp | |

Merge: the union of all reviews. Insert by `id` and ignore duplicates.

Quiz answers are reviews too, recorded when a quiz is submitted:
- wrong → 1
- right but low confidence (confidence 1) → 2
- right → 3

In exam mode, unanswered questions count as wrong. In practice mode, unanswered questions are skipped. See `_submit` in `backend/app/api/quiz.py`.

### `srs/{itemId}`: both sides
| field | type | |
|---|---|---|
| itemId | string | |
| scheduler | string | `fsrs` (default) or `sm2` (decks imported from StudyDeck v1) |
| state | string (JSON) | fsrs: py-fsrs 6 `Card.to_dict()`, i.e. `{card_id, state, step, stability, difficulty, due, last_review}` (ISO strings). sm2: `{ef, reps, interval}` |
| due | timestamp | |
| lastReviewedAt | timestamp | time of the review that produced this state |
| device | string | |
| syncedAt | server timestamp | |

Merge: **the doc with the later `lastReviewedAt` wins.**
- When writing, only overwrite a doc whose `lastReviewedAt` is older than yours. Do it inside a transaction (phone) or with an `updateTime` precondition (web).
- When pulling, apply a doc only if it is newer than your local copy.
- If both devices review the same card while offline, the earlier review stays in `reviews` but doesn't affect the schedule.

FSRS settings must match the web app: py-fsrs 6 defaults, desired retention 0.9. Fuzzing is allowed. `fixtures/fsrs_golden.json` pins the behaviour without fuzzing.

### `attempts/{attemptId}`: both sides; **create-only**; submitted attempts only
| field | type | |
|---|---|---|
| id, exam, packId, mode, device | string | mode `practice` or `exam` |
| submittedAt | timestamp | |
| score, total | int | |
| body | string (JSON) | see below |
| syncedAt | server timestamp | |

```json
{
  "attempt": {"id": "...", "name": "...", "mode": "practice", "packId": "...", "quizId": null,
              "exam": "...", "itemIds": ["..."], "startedAt": "ISO", "deadlineAt": null,
              "submittedAt": "ISO", "score": 7, "total": 10},
  "responses": [{"itemId": "...", "choiceIds": ["A"], "text": null, "correct": true, "flagged": false,
                 "confidence": 3, "timeMs": 5400, "answeredAt": "ISO"}]
}
```

Merge: insert if the id is unknown. Each client remembers which attempt ids it has already synced, so a local delete stays deleted.

### `subjects/`, `decks/`, `cards/`
These are StudyDeck's own decks, unchanged. The web app doesn't touch them.
