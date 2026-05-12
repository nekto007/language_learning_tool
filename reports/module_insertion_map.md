# Module Insertion Map

Generated for Task 5 of `docs/plans/2026-05-11-post-immersion-content-data-plan.md`.

Source: `module_completed/fixed/` (77 modules, A1–C1).
CSV: `content/immersion/module_insertion_map.csv`.

## Purpose

Defines the canonical insertion points for the three slot-critical immersion
lesson types (`dictation`, `writing_prompt`, `shadow_reading`) inside every
source module. Used by the importer in Tasks 17 / 19 / 21 to place new
lessons at deterministic, conflict-free orders.

## Source module summary

| Level | Modules |
|-------|---------|
| A1 | 16 |
| A2 | 22 |
| B1 | 14 |
| B2 | 12 |
| C1 | 13 |
| **Total** | **77** |

Every source module has exactly 12 lessons in this canonical sequence:

| Order | Type |
|-------|------|
| 1 | `vocabulary` |
| 2 | `flashcards` |
| 3 | `grammar` |
| 4 | `quiz` |
| 5 | `reading` |
| 6 | `listening_quiz` |
| 7 | `dialogue_completion_quiz` |
| 8 | `ordering_quiz` |
| 9 | `flashcards` |
| 10 | `translation_quiz` |
| 11 | `listening_immersion` |
| 12 | `final_test` |

Because the sequence is uniform across all 77 modules, the per-module insertion
points are uniform as well. The CSV still emits one row per module so the
importer can resolve module identity (filename, source id, level, module
number, title, title_en) without re-parsing the source files.

## Insertion rules

Each new lesson type has a primary anchor type and a fallback anchor type.
The importer uses the anchor_position (`after`/`before`) to compute the
final insertion index.

| New lesson type | Primary anchor | Position | Fallback anchor | Position |
|-----------------|---------------|----------|-----------------|----------|
| `dictation` | `listening_quiz` | `after` | `listening_immersion` | `before` |
| `writing_prompt` | `translation_quiz` | `after` | `final_test` | `before` |
| `shadow_reading` | `listening_immersion` | `after` | `final_test` | `before` |

Anchor rationale:
- `dictation` complements the existing `listening_quiz` block and stays clear
  of the dialogue/ordering quiz cluster, so it goes immediately after
  `listening_quiz`.
- `writing_prompt` consumes module vocabulary and grammar, so it lands after
  the `translation_quiz` (the productive-output pivot) and before the
  `final_test`.
- `shadow_reading` extends `listening_immersion` (same audio/transcript axis)
  and sits between immersion and the `final_test`.

## Final lesson order after all three inserts

| Order | Type |
|-------|------|
| 1 | `vocabulary` |
| 2 | `flashcards` |
| 3 | `grammar` |
| 4 | `quiz` |
| 5 | `reading` |
| 6 | `listening_quiz` |
| 7 | **`dictation` (new)** |
| 8 | `dialogue_completion_quiz` |
| 9 | `ordering_quiz` |
| 10 | `flashcards` |
| 11 | `translation_quiz` |
| 12 | **`writing_prompt` (new)** |
| 13 | `listening_immersion` |
| 14 | **`shadow_reading` (new)** |
| 15 | `final_test` |

- Total lessons per module after import: 15.
- `final_test` remains in the final slot for all 77 modules — verified by the
  `final_test_remains_final=true` column in the CSV.
- The original lessons keep their relative order; only the absolute `order`
  number changes for lessons after each insertion point.

## CSV schema

`content/immersion/module_insertion_map.csv` columns:

| Column | Notes |
|--------|-------|
| `level` | CEFR level from filename (`A1`, `A2`, `B1`, `B2`, `C1`). |
| `module_number` | `module.order` from the source JSON. |
| `source_module_id` | `module.id` from the source JSON. |
| `source_filename` | e.g. `module_A1_1_greetings.json`. |
| `title` | Russian title from source. |
| `title_en` | English title from source. |
| `current_lesson_count` | Always 12 in the current snapshot. |
| `dictation_anchor_type` | `listening_quiz`. |
| `dictation_anchor_position` | `after`. |
| `dictation_target_order` | `7` for all modules. |
| `writing_prompt_anchor_type` | `translation_quiz`. |
| `writing_prompt_anchor_position` | `after`. |
| `writing_prompt_target_order` | `12` for all modules. |
| `shadow_reading_anchor_type` | `listening_immersion`. |
| `shadow_reading_anchor_position` | `after`. |
| `shadow_reading_target_order` | `14` for all modules. |
| `final_test_remains_final` | `true` for all modules. |

## DB reconciliation note

The DB snapshot checked on 2026-05-11 holds 76 modules, while the source has 77
(see `reports/immersion_data_audit.md`). The insertion map covers all 77
source modules; the importer skips source modules that have no matching DB
module and logs them as `not_in_db` in the per-import report (Tasks 17 / 19 / 21).
No mass renumbering is required because:
1. All target orders fall strictly between existing lesson orders.
2. The importer must shift downstream lessons by `+1` per insertion (i.e. the
   first lesson with `order >= target_order` and every subsequent lesson get
   their `order` incremented).
3. The shifts are deterministic and per-module, so re-running the importer is
   idempotent provided each insertion is keyed on a stable `external_key`
   (Tasks 10 / 11).

## Exceptions

None. Every source module follows the canonical 12-lesson layout and accepts
the three insertion points without restructuring. If a future module breaks
this assumption, regenerate the CSV — the script that produced it reads the
actual `lessons[*].type` list per module and recomputes anchors and targets
on the fly.
