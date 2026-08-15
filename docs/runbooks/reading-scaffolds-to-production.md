# Reading Scaffolds to Production

Moves finished reading-lesson scaffolds from the environment they were
generated in to production.

Scope:

- One column of one table: `daily_lessons.annotations`, for lessons whose
  `lesson_type` is one of `reading`, `reading_assignment`, `reading_passage`,
  `reading_part1`, `reading_part2`.
- Tool: `scripts/generate_reading_annotations.py`, subcommands `dump` and
  `load`.
- Nothing else is written. No course, module, lesson or task is created,
  updated or deleted, and no user-generated row is touched.

Do **not** use `scripts/import_book_course.py` for this: it recreates a whole
course, and its `--force` deletes the course with the same slug — on
production that destroys the lessons users are studying.

---

## 0. Preconditions

- `master` contains the `dump`/`load` subcommands, and the production host has
  pulled it.
- **The script still has to be copied into the container.** `Dockerfile`
  (lines 19-25) copies only `run.py`, `cli.py`, `babel.cfg`,
  `convert_fb2_to_txt.py`, `app/`, `config/` and `migrations/`; `scripts/` and
  `work/` are not in the image and are not mounted by `docker-compose.yml`.
  A `git pull` alone therefore does not make `load` runnable — step 3 does.
- `work/` and `content/` are gitignored, so the fixture travels out of band
  (scp). Record which dump was applied in the rollout note.
- On the source host, `status` shows what is available to ship, and `dump`
  exits 0.

State of the source environment as of 2026-08-15: all 1033 reading lessons carry
a scaffold and all 1033 validate against their own passage, so `dump` ships the
complete set (5.9 MB across 9 course files). The 204 scaffolds the first dump
rejected — quotes that were not verbatim, missing `quick_use`, `self_check` with
two items — were regenerated through the offline pipeline
(`export --invalid-only` → generate → `check` → `import --overwrite`).

---

## 1. Take a rollback point

The fixture only adds; a rollback needs the previous state of the column.

```bash
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "CREATE TABLE annotations_backup_$(date +%Y%m%d) AS
   SELECT id, annotations FROM daily_lessons WHERE annotations IS NOT NULL;"
```

Verification — the row count is the number of scaffolds production has now:

```bash
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM annotations_backup_$(date +%Y%m%d);"
```

Record the count and the table name. Both are needed by §5.

---

## 2. Dump on the source host

```bash
python scripts/generate_reading_annotations.py dump
```

Expected: one file per course under `work/reading_scaffolds_fixture/`, and
`Wrote N course file(s), 0 invalid, 0 unaddressable.` A non-zero `invalid`
count is not a blocker — those lessons are simply left out — but note the
number, because it is the regeneration backlog.

---

## 3. Copy the fixture and the script to production

```bash
# On the source host
tar -czf reading_scaffolds_fixture.tgz -C work reading_scaffolds_fixture
scp reading_scaffolds_fixture.tgz <user>@<prod-host>:<project-dir>/work/

# On the production host, in the project directory
tar -xzf work/reading_scaffolds_fixture.tgz -C work/

# Into the running container (see §0 — the image has neither directory)
docker compose exec web mkdir -p /app/scripts /app/work
docker cp scripts/generate_reading_annotations.py \
  language_learning_tool_web:/app/scripts/generate_reading_annotations.py
docker cp work/reading_scaffolds_fixture \
  language_learning_tool_web:/app/work/reading_scaffolds_fixture
```

Verification:

```bash
docker compose exec web ls /app/work/reading_scaffolds_fixture
```

---

## 4. Dry run, then load

`load` matches lessons by course slug, module number, day number and lesson
type — never by id, which differs between databases — compares a fingerprint of
the passage, and re-validates every quote against the passage stored in *this*
database before writing.

```bash
docker compose exec web python scripts/generate_reading_annotations.py \
  load --dry-run
```

Read the summary before going further:

| line | meaning | action |
| ---- | ------- | ------ |
| `N to write` | lessons that will get a scaffold | expected count |
| `N already had a scaffold` | production has its own version | rerun with `--overwrite` to replace it, see the risk in §6 |
| `N unmatched` | no lesson with that key here | stop and investigate: the module/day coordinates differ between environments |
| `N passage drift` | the passage here is not the one the scaffold was written for | stop; regenerate for the current text rather than forcing |
| `N invalid` | quotes are not verbatim in this database's passage | stop; never load these |

`--dry-run` exits non-zero if any of the last three appear, so a deploy step
can gate on it.

Only when the dry run is clean:

```bash
docker compose exec web python scripts/generate_reading_annotations.py load
```

Expected: `Done: N written.` and exit 0.

---

## 5. Verify

```bash
docker compose exec web python scripts/generate_reading_annotations.py status
```

`done` must have grown by exactly the `written` count from §4, and `pending`
must have dropped by the same number.

Then open one reading lesson in the browser and confirm the six sections
render: objectives, before-reading goal and tasks, the notes under the text,
the reflection questions, the true/false self-check, and the can-do list. The
template is `app/templates/curriculum/book_courses/lessons/reading_passage.html`.

---

## 6. Rollback

Restores the column to the state captured in §1 — first the rows that had a
scaffold, then the rows that had none and were written by this rollout.

```bash
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "UPDATE daily_lessons dl SET annotations = b.annotations
   FROM annotations_backup_<TS> b WHERE dl.id = b.id;"

docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "UPDATE daily_lessons SET annotations = NULL
   WHERE annotations IS NOT NULL
     AND id NOT IN (SELECT id FROM annotations_backup_<TS>);"
```

Verify with `status` — `done` must match the count recorded in §1. Drop the
backup table only after the rollout is accepted.

---

## 7. Risks

- **`--overwrite` replaces a scaffold production already has.** Every quote is
  re-validated against production's own passage first, so an overwrite cannot
  introduce a quote that is not in the text — but the replaced version exists
  only in the §1 snapshot. Never run it without that snapshot.
- **Unmatched keys are a content divergence, not a fixture bug.** They mean the
  two databases disagree about which module or day a lesson belongs to.
  Forcing the load would put a scaffold on the wrong passage; there is no flag
  that does this, and none should be added.
- **`--allow-passage-drift` weakens the strongest check.** It only bypasses the
  fingerprint; the quote validation still runs. Even so, the reflection
  questions and self-check statements describe the old text, so prefer
  regenerating.
- **The fixture is not in git.** Two hosts can hold different dumps with the
  same file names. Note the dump date in the rollout record.
- **`load` is idempotent.** Re-running it writes nothing new: everything it
  already stored comes back as `already had a scaffold`.

---

## 8. Cross-references

- `scripts/generate_reading_annotations.py` — `status`, `export`, `check`,
  `import`, `dump`, `load`.
- `tests/scripts/test_generate_reading_annotations.py` — the validation rules
  and every `decide_load` outcome named in §4.
- `docs/runbooks/immersion-data-rollback.md` — full-dump backup procedure when
  a rollout touches more than this one column.
- `app/templates/curriculum/book_courses/lessons/reading_passage.html` — the
  six sections verified in §5.
