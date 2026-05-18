# A1/M1 canonical reference reconciliation

Reconciles `module_completed/fixed/module_A1_1_greetings.json` against the
live local DB (`A1` → `module.number = 1`) so the source JSON can serve as
the canonical quality bar for the rest of Task 1+.

- Source file: `module_completed/fixed/module_A1_1_greetings.json`
- DB target:  `lessons` where `module_id = (level=A1, number=1)`
- Reconciliation date: 2026-05-18
- Direction of merge: DB → JSON (approved DB shape pulled back into JSON)
- Identity policy: `content.external_key` becomes the stable lesson identity.
  Source-local `id`/`number`/`order` are presentation/order fields only.

## TL;DR

- 18 lessons match between DB and JSON.
- 1 lesson (`grammar`) had a legacy-shape JSON payload that has been replaced
  with the new schema (`rule` / `sections` / `exercises` / `summary` / `tldr` /
  `important_notes` / `description` / `examples` / `title`).
- 7 new-style lessons already carried `content.external_key` in both DB and
  JSON.
- 10 legacy-style lessons (vocabulary, both flashcards, grammar, reading,
  listening_immersion, listening_quiz, dialogue_completion_quiz,
  ordering_quiz, translation_quiz, final_test) were missing
  `content.external_key`; stable keys under the
  `curriculum:<type>:A1:01:<slug>` namespace have been added to the source
  JSON. These are intentionally JSON-leading — the next import will sync
  them into the DB.
- Audio reference drift (filename mismatches on reading line audio and
  listening_immersion audio, plus missing per-item `audio_clip_url` on
  audio_fill_blank) was fixed by adopting the DB values, which point at the
  files actually generated during the previous rollout.
- Two listening_quiz exercise texts (#4 instruction + question) were fixed
  to match the DB phrasing.
- Display metadata mirrored DB-only fields back into JSON: `note`,
  `settings` on flashcards lessons; `content.xp_reward` where DB had it;
  `audio_url` and `duration_seconds` on listening_immersion.
- `cards[].word_id` on flashcards lessons was intentionally NOT mirrored:
  it is a local DB `Word.id` foreign key and would couple the source JSON
  to a specific environment.

## Lesson sequence

The current sequence already matches the canonical target order from the
plan (18 lessons). No reorder was needed.

| #  | type                       | title (Russian)                                       | external_key                                                       |
| -- | -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------ |
| 1  | vocabulary                 | Привет! Hello!                                        | curriculum:vocabulary:A1:01:greetings                              |
| 2  | flashcards                 | Карточки: Слова и фразы                               | curriculum:flashcards:A1:01:greetings_main                         |
| 3  | collocation_matching       | Сочетания: знакомство и приветствия                   | immersion:collocation_matching:A1:01:greetings_introductions       |
| 4  | grammar                    | Глагол BE (am/is/are)                                 | curriculum:grammar:A1:01:to_be                                     |
| 5  | sentence_completion        | Завершение предложений: глагол to be                  | immersion:sentence_completion:A1:01:to_be                          |
| 6  | reading                    | Чтение: Новые друзья                                  | curriculum:reading:A1:01:new_friends                               |
| 7  | listening_immersion        | Слушаем диалог                                        | curriculum:listening_immersion:A1:01:coffee_shop                   |
| 8  | listening_quiz             | Аудирование: Слушаем и понимаем                       | curriculum:listening_quiz:A1:01:greetings                          |
| 9  | audio_fill_blank           | Аудио: Приветствия и знакомство                       | immersion:audio_fill_blank:A1:01:greetings                         |
| 10 | shadow_reading             | Теневое чтение: Знакомство и приветствия              | immersion:shadow_reading:A1:01:greetings                           |
| 11 | dictation                  | Диктант: Знакомство и приветствия                     | immersion:dictation:A1:01:greetings                                |
| 12 | dialogue_completion_quiz   | Дополни диалог                                        | curriculum:dialogue_completion_quiz:A1:01:greetings                |
| 13 | ordering_quiz              | Порядок слов в предложении                            | curriculum:ordering_quiz:A1:01:to_be_word_order                    |
| 14 | flashcards                 | Карточки: Повторение                                  | curriculum:flashcards:A1:01:greetings_review                       |
| 15 | translation                | Перевод: Знакомство                                   | immersion:translation:A1:01:introductions                          |
| 16 | translation_quiz           | Переводим на английский                               | curriculum:translation_quiz:A1:01:greetings                        |
| 17 | writing_prompt             | Письмо: Знакомство и приветствия                      | immersion:writing_prompt:A1:01:greetings                           |
| 18 | final_test                 | Итоговый тест модуля                                  | curriculum:final_test:A1:01:to_be                                  |

Note: `flashcards` in JSON maps to `card` in DB through the existing import
service alias (`app/admin/services/curriculum_import_service.py`, line 274:
`'flashcards': 'card'`).

## Content-sensitive fields (Task 0 checklist)

Per the Task 0 checklist, the following fields were audited explicitly:

| Field group                       | Lesson                | Status after reconciliation                                            |
| --------------------------------- | --------------------- | ---------------------------------------------------------------------- |
| translation `items[]` + `mode`    | #15 translation       | OK — `items[]` present, no `mode` in DB or JSON (both consistent)      |
| writing_prompt full new shape     | #17 writing_prompt    | OK — `prompt_ru`, `min_sentences`, `template`, `hint_words`,           |
|                                   |                       | `target_phrases`, `mode`, `checklist`, `example_response` all present  |
| sentence_correction `mode`        | (not in module)       | N/A — this module uses `sentence_completion` instead                   |
| audio_fill_blank item audio       | #9 audio_fill_blank   | FIXED — 5 `audio_clip_url` values backfilled from DB                   |
| dictation gap/transcript fields   | #11 dictation         | OK — `audio_text`, `transcript`, `gap_text`, `gaps[]`, `hint_chars`,   |
|                                   |                       | `mode`, `duration_seconds`, `audio_url`, `external_key` all present    |
| final_test phrasing + matching    | #18 final_test        | OK — DB phrasing already in JSON; no matching pair section in module   |

## Drift fixes (DB → JSON)

45 audit entries were applied in total. Grouped:

### Grammar lesson rewrite (#4)

JSON had the legacy `grammar_explanation` nested object. DB had the new
schema. The JSON now mirrors the DB:

- Removed: `content.grammar_explanation`.
- Added (from DB): `rule`, `description`, `examples`, `exercises`,
  `important_notes`, `sections`, `summary`, `title`, `tldr`, `xp_reward`.

This makes A1/M1 a real reference for the new grammar shape. Modules whose
JSON still uses `grammar_explanation` will be caught by the Task 1 audit.

### Audio reference sync

- `#6 reading.text.lines[0..7].audio`: JSON used `[sound:A1M1L6_line_*.mp3]`,
  DB used `[sound:A1M1L5_line_*.mp3]`. The L5 paths point at the audio
  generated during the previous rollout. JSON now uses L5.
- `#7 listening_immersion.audio`: JSON used `[sound:A1_M1_L7_dialogue.mp3]`,
  DB used `[sound:A1_M1_L11_dialogue.mp3]`. JSON now uses L11.
- `#7 listening_immersion.audio_url` and `.duration_seconds` were missing
  in JSON. JSON now includes `/static/audio/A1_M1_L11_dialogue.mp3` and
  `54` seconds.
- `#9 audio_fill_blank.items[0..4].audio_clip_url`: missing in JSON, added
  from DB.

### Text content sync

- `#8 listening_quiz.exercises[4]`:
  - `instruction`: `'Прослушайте фразу и выберите перевод'` →
    `'Прослушайте фразу и выберите правильный вариант'`
  - `question`: `'Where are you from?'` →
    `'Что означает эта фраза?'`
- These match the DB phrasing and the actual audio the lesson references.

### External keys (JSON-leading additions)

For the 10 legacy-type lessons that previously had no
`content.external_key`, stable identity keys have been added to JSON under
the `curriculum:<type>:A1:01:<slug>` namespace. Both flashcards lessons
are distinguished by slug (`greetings_main` for #2, `greetings_review` for
#14) so position changes will never silently merge them.

These keys are not yet in the DB. The Task 7 import/diff verification
step is responsible for promoting them into the DB without overwriting
existing rows. Until then, the existing DB rows continue to resolve by
`(module_id, number)`.

### Mirrored display metadata

- `content.xp_reward` was mirrored into JSON for every lesson where DB had
  it: 50 for vocabulary/flashcards/collocation_matching/listening_immersion/
  flashcards-review, 75 for grammar/listening_quiz/dialogue_completion_quiz/
  ordering_quiz/translation_quiz.
- `note: ""` and `settings: {}` added to both flashcards lessons.

## Intentional drift (documented, NOT applied)

- `flashcards #14 cards[].word_id`: DB has integer FKs into the local
  `words` table (e.g. 7533, 7775, 8579, 4180, 25106, 5304, 8342). These
  IDs would not be portable to staging/production. JSON keeps the cards
  without `word_id`; the importer is expected to resolve cards by
  `(english, russian)` or by an explicit per-card slug.
- `flashcards #2 cards[].word_id`: same rationale.
- 10 newly-added `content.external_key` values are intentionally JSON-only
  until the next import promotes them.

## Verification

Re-running the deep DB↔JSON diff after the reconciliation:

```
$ python <verify-script>
#1  vocabulary                 1 diff  [JSON-ONLY external_key] (expected)
#2  flashcards                 1 diff  [JSON-ONLY external_key] (expected)
#4  grammar                    1 diff  [JSON-ONLY external_key] (expected)
#6  reading                    1 diff  [JSON-ONLY external_key] (expected)
#7  listening_immersion        1 diff  [JSON-ONLY external_key] (expected)
#8  listening_quiz             1 diff  [JSON-ONLY external_key] (expected)
#12 dialogue_completion_quiz   1 diff  [JSON-ONLY external_key] (expected)
#13 ordering_quiz              1 diff  [JSON-ONLY external_key] (expected)
#14 flashcards                 8 diffs [JSON-ONLY external_key + 7 DB-only word_id] (expected)
#16 translation_quiz           1 diff  [JSON-ONLY external_key] (expected)
#18 final_test                 1 diff  [JSON-ONLY external_key] (expected)
```

All other lessons are byte-identical between DB and JSON. The remaining 18
"diff items" are all intentional and documented above.

## Sign-off

A1/M1 is now a real canonical reference for the rest of the rollout:

- New-style lessons retain their existing `immersion:*` external keys.
- Legacy-style lessons now carry stable `curriculum:*` external keys.
- The grammar lesson now uses the new schema.
- All audio references point at files the previous rollout actually
  generated.
- The only DB-only items are non-portable local FKs (`word_id`), which are
  explicitly out-of-scope for a portable JSON source layer.

Task 1 may begin using `module_A1_1_greetings.json` as the canonical
quality bar for the rest of A1, A2, B1, B2, C1.
