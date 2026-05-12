# docs/runbooks

Operational runbooks for the immersion rollout and adjacent data work.
Runbooks are procedural — they tell an on-call engineer exactly which
commands to run, in which order, and how to verify the result.

Companion documents:

- `docs/content/README.md` — content authoring conventions and the
  acceptance contract in `immersion-content-targets.md`.
- `docs/plans/2026-05-11-post-immersion-content-data-plan.md` — the
  task list that produced these runbooks.

## Active runbooks

| File                              | Scope                                                                  | Trigger                                        |
| --------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------- |
| `immersion-data-rollback.md`      | Backup + rollback for `lessons`, `collection_words`, `word_collocations`, `cultural_notes`, `user_card_directions`. | Before any immersion content import.           |
| `immersion-data-readiness.md`     | Production-readiness checklist (Task 8). Import order, audits, smoke URLs, rollback checkpoints. | Before staging or production rollout.          |

Add new runbooks as separate files. Do not bury procedures inside the
plan or inside content READMEs — runbooks must be findable by
on-call.

## What belongs in `docs/runbooks`

- Concrete commands to run, with environment variables and expected
  output.
- Verification steps that produce checkable evidence (row counts,
  HTTP responses, file hashes).
- Rollback paths for every destructive step.
- Risk callouts for user-generated data that must never be
  overwritten from a backup.

## What does NOT belong here

- Architectural rationale. That belongs in `docs/decisions/` or the
  plan.
- Lesson schemas or content targets. Those belong in `docs/content/`.
- Test plans. Those belong in `docs/qa/`.
- Long narrative explanations of why a fix was applied. Use the
  commit message or a review note.

## Runbook structure

Every runbook follows this layout:

1. **Title and scope.** What systems and tables the runbook
   touches.
2. **Preconditions.** Required env vars, access, prior backups.
3. **Step-by-step procedure.** Numbered. Each step has a command, a
   verification, and an expected outcome. Commands are copy-paste
   ready.
4. **Rollback.** Mirror of the procedure, ordered to leave the
   system in a clean state on failure.
5. **Risks.** User-generated tables, idempotency assumptions, data
   that cannot be restored.
6. **Cross-references.** Links to the importers, audits, reports,
   and acceptance contract this runbook depends on.

## Cross-references

- Importers: `scripts/import_immersion_lessons.py`,
  `scripts/import_lesson_audio_metadata.py`,
  `scripts/import_frequency_bands.py`,
  `scripts/import_ipa_transcriptions.py`,
  `scripts/import_synonyms_antonyms.py`,
  `scripts/import_word_collocations.py`,
  `scripts/import_etymology_notes.py`,
  `scripts/import_cultural_notes.py`,
  `scripts/backfill_card_sources.py`.
- Audits: `scripts/audit_immersion_data.py`,
  `scripts/audit_existing_listening_payloads.py`.
- Reports: see `docs/content/README.md` "Report generation conventions".
- Acceptance contract: `docs/content/immersion-content-targets.md`.
