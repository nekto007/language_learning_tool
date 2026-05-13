# Vocabulary Enrichment Coverage Report

> This file is a placeholder. Generate the live report against the DB by running:
>
>     python scripts/report_vocabulary_enrichment.py --output reports/vocabulary_enrichment.md
>
> For JSON output:
>
>     python scripts/report_vocabulary_enrichment.py --format json --output reports/vocabulary_enrichment.json

## Fields Tracked

| Field | Source table / column |
|---|---|
| ipa_transcription | collection_words.ipa_transcription |
| frequency_band | collection_words.frequency_band |
| synonyms | collection_words.synonyms |
| antonyms | collection_words.antonyms |
| etymology | collection_words.etymology |
| collocations | word_collocations (child table, ≥1 row per word) |
| cultural_notes | cultural_notes (child table, ≥1 row per word) |

## Priority Tier Definition

The report breaks coverage down by priority tier (same logic as `scripts/export_vocabulary_priority.py`):

- Tier 1 (highest): level in {A1, A2} OR curriculum_lessons ≥ 2 OR user_count ≥ 3
- Tier 2 (medium): level in {B1, B2} OR curriculum_lessons = 1 OR user_count in {1, 2}
- Tier 3 (low): everything else

## Expected State (2026-05-11 baseline)

Based on the immersion data audit, before any enrichment imports:

- collection_words rows: 24,853
- ipa_transcription filled: 0
- frequency_band filled: 0
- synonyms filled: 0
- antonyms filled: 0
- etymology filled: 0
- word_collocations rows: 0
- cultural_notes rows: 0

After running enrichment imports (tasks 36-41), re-run this script to measure actual coverage.
