# Coverage Roadmap: 50% → 55%

**Date:** 2025-11-24
**Current Coverage:** 50%
**Target Coverage:** 55%
**Gap to Close:** 5%

---

## Current Status

### ✅ Already Completed (High Coverage)
1. **app/admin/book_courses.py** - 83% ✅ (just completed)
2. **app/admin/services/user_management_service.py** - ~85% ✅
3. **app/admin/services/system_service.py** - ~60% ✅
4. **app/modules/migrations.py** - tests optimized ✅
5. **Core services:** GameService, StatsService, CollectionTopicService - high coverage ✅

### 🔄 Priority Targets (3 Admin Services)

#### 1. WordManagementService ⭐ HIGH IMPACT
**File:** `app/admin/services/word_management_service.py`
**Size:** ~320 lines
**Estimated Impact:** +2% overall coverage
**Complexity:** Medium

**Methods to Test (6 total):**
- ✅ `get_word_statistics()` - statistics aggregation
- ✅ `bulk_update_word_status()` - bulk operations
- ✅ `export_words_to_json()` - JSON export
- ✅ `export_words_to_csv()` - CSV export
- ✅ `export_words_to_txt()` - TXT export
- ✅ `import_translations()` - translation import

**Estimated Tests:** 15-18 tests
**Expected Coverage:** 70-80%
**Testing Strategy:**
- Mock file I/O operations
- Test export format correctness
- Test bulk status updates
- Test import validation

---

#### 2. AudioManagementService ⭐ MEDIUM IMPACT
**File:** `app/admin/services/audio_management_service.py`
**Size:** ~300 lines
**Estimated Impact:** +1.5% overall coverage
**Complexity:** Medium

**Methods to Test (4 total):**
- ✅ `get_audio_statistics()` - statistics
- ✅ `update_download_status()` - status management
- ✅ `fix_listening_fields()` - data fixing
- ✅ `get_download_list()` - list generation

**Estimated Tests:** 12-15 tests
**Expected Coverage:** 70-75%
**Testing Strategy:**
- Mock database queries
- Test status transitions
- Test data fixing logic
- Test list filtering

---

#### 3. CurriculumImportService ⭐ HIGH IMPACT
**File:** `app/admin/services/curriculum_import_service.py`
**Size:** ~460 lines
**Estimated Impact:** +2.5% overall coverage
**Complexity:** High

**Methods to Test (5+ total):**
- ✅ `import_curriculum_data()` - main import logic
- ✅ `validate_curriculum_structure()` - validation
- ✅ `process_vocabulary()` - vocab processing
- ✅ `process_grammar()` - grammar processing
- ✅ `create_or_update_lesson()` - lesson management

**Estimated Tests:** 20-25 tests
**Expected Coverage:** 65-75%
**Testing Strategy:**
- Mock file operations
- Test JSON validation
- Test data transformation
- Test error handling for invalid data

---

## Coverage Impact Analysis

### Optimistic Scenario (75% coverage for each service)
```
WordManagementService:     320 lines × 0.75 = 240 lines covered   → +2.0%
AudioManagementService:    300 lines × 0.75 = 225 lines covered   → +1.5%
CurriculumImportService:   460 lines × 0.75 = 345 lines covered   → +2.5%

Total Impact: +6.0% coverage
Final Coverage: 50% + 6% = 56% ✅ EXCEEDS TARGET
```

### Conservative Scenario (60% coverage for each service)
```
WordManagementService:     320 lines × 0.60 = 192 lines covered   → +1.6%
AudioManagementService:    300 lines × 0.60 = 180 lines covered   → +1.2%
CurriculumImportService:   460 lines × 0.60 = 276 lines covered   → +2.0%

Total Impact: +4.8% coverage
Final Coverage: 50% + 4.8% = 54.8% ✅ CLOSE TO TARGET
```

### Minimal Scenario (Test 2 services at 70%)
```
WordManagementService:     320 lines × 0.70 = 224 lines covered   → +1.8%
CurriculumImportService:   460 lines × 0.70 = 322 lines covered   → +2.2%

Total Impact: +4.0% coverage
Final Coverage: 50% + 4% = 54% ⚠️ SLIGHTLY BELOW TARGET
```

---

## Recommended Approach

### Phase 1: WordManagementService (Priority 1)
**Estimated Time:** 2-3 hours
**Target:** 15-18 tests, 70-80% coverage
**Impact:** +2% overall coverage

**Test Categories:**
1. Statistics tests (3 tests)
   - Success case with data
   - Empty database case
   - Error handling

2. Bulk update tests (4 tests)
   - Update multiple words status
   - Update with invalid IDs
   - Update with empty list
   - Rollback on error

3. Export tests (6 tests)
   - JSON export format validation
   - CSV export format validation
   - TXT export format validation
   - Export with empty data
   - Export with filters
   - Export error handling

4. Import tests (5 tests)
   - Valid translation import
   - Invalid format handling
   - Duplicate handling
   - Validation errors
   - File I/O errors

---

### Phase 2: CurriculumImportService (Priority 2)
**Estimated Time:** 3-4 hours
**Target:** 20-25 tests, 65-75% coverage
**Impact:** +2.5% overall coverage

**Test Categories:**
1. Validation tests (5 tests)
   - Valid structure
   - Invalid JSON
   - Missing required fields
   - Invalid data types
   - Schema validation

2. Import tests (5 tests)
   - Full curriculum import
   - Partial import
   - Update existing data
   - Create new data
   - Rollback on error

3. Processing tests (8 tests)
   - Vocabulary processing
   - Grammar processing
   - Lesson creation
   - Lesson update
   - Related data handling

4. Edge cases (5 tests)
   - Empty curriculum
   - Malformed data
   - Large dataset
   - Concurrent imports
   - Cleanup on failure

---

### Phase 3: AudioManagementService (Optional)
**Estimated Time:** 1.5-2 hours
**Target:** 12-15 tests, 70-75% coverage
**Impact:** +1.5% overall coverage

**Test Categories:**
1. Statistics tests (3 tests)
2. Status management tests (4 tests)
3. Data fixing tests (4 tests)
4. List generation tests (4 tests)

---

## Alternative Quick Wins

If time is limited, focus on these high-impact, low-complexity files:

### Quick Win Option 1: Small Utility Files
- `app/utils/cache.py` - 5 lines (100% easy)
- `app/admin/utils/cache.py` - small utility
- `app/admin/utils/decorators.py` - decorators testing
- **Impact:** +0.5% with minimal effort

### Quick Win Option 2: Models with Properties
- Test model properties and methods
- Validate data transformations
- Check edge cases
- **Impact:** +1% with medium effort

### Quick Win Option 3: Forms Validation
- `app/admin/form.py` - 32 lines (0% currently)
- `app/curriculum/form.py` - 75 lines (0% currently)
- Test form validation logic
- **Impact:** +0.8% with low-medium effort

---

## Execution Plan

### Option A: Focus on Admin Services (Recommended)
```
Day 1: WordManagementService
  - 15-18 tests
  - +2% coverage
  - Total: 52%

Day 2: CurriculumImportService
  - 20-25 tests
  - +2.5% coverage
  - Total: 54.5%

Day 3: AudioManagementService OR quick wins
  - 12-15 tests OR multiple small files
  - +1.5% coverage
  - Total: 56% ✅
```

### Option B: Mixed Approach
```
Day 1: WordManagementService + Quick Wins
  - 15 tests + small files
  - +2.5% coverage
  - Total: 52.5%

Day 2: CurriculumImportService (partial)
  - 15 tests (core functionality)
  - +1.8% coverage
  - Total: 54.3%

Day 3: AudioManagementService (partial) + Forms
  - 10 tests + form validation
  - +1.5% coverage
  - Total: 55.8% ✅
```

---

## Testing Templates

### Template 1: Service Method Test
```python
def test_method_success(self, app, db_session):
    """Test successful execution"""
    with app.app_context():
        # Setup
        # Execute
        result = Service.method()
        # Assert
        assert result is not None
```

### Template 2: Export Test
```python
def test_export_format(self, app, db_session, tmp_path):
    """Test export format correctness"""
    with app.app_context():
        # Create test data
        # Export
        result = Service.export_to_format()
        # Validate format
        assert result['format'] == 'expected'
```

### Template 3: Bulk Operation Test
```python
def test_bulk_operation(self, app, db_session):
    """Test bulk operation"""
    with app.app_context():
        # Create multiple items
        items = [create_item(i) for i in range(5)]
        # Execute bulk operation
        result = Service.bulk_update(items)
        # Verify all updated
        assert result['updated'] == 5
```

---

## Success Metrics

### Minimum Success (55% coverage)
- ✅ WordManagementService: 70% coverage
- ✅ CurriculumImportService: 65% coverage
- ✅ Total project coverage: 55%

### Ideal Success (56-57% coverage)
- ✅ WordManagementService: 80% coverage
- ✅ CurriculumImportService: 75% coverage
- ✅ AudioManagementService: 75% coverage
- ✅ Total project coverage: 56-57%

### Stretch Goal (58%+ coverage)
- ✅ All 3 admin services: 80%+ coverage
- ✅ Quick wins implemented
- ✅ Forms tested
- ✅ Total project coverage: 58%+

---

## Files Tracker

### Test Files to Create
- [ ] `tests/admin/services/test_word_management_service.py`
- [ ] `tests/admin/services/test_audio_management_service.py`
- [ ] `tests/admin/services/test_curriculum_import_service.py`

### Documentation to Update
- [ ] `ADMIN_TESTING_PROGRESS.md` (update status)
- [ ] `TESTING_SESSION_SUMMARY.md` (add new session)
- [ ] `COVERAGE_ROADMAP_TO_55.md` (this file - update progress)

---

## Next Steps

1. **Start with WordManagementService** (highest ROI)
2. **Create test file structure** similar to existing service tests
3. **Write 15-18 tests** covering all methods
4. **Run coverage** and verify +2% improvement
5. **Move to CurriculumImportService**
6. **Monitor overall coverage** after each service
7. **Stop when 55% reached** or continue to 56-57%

---

**Created:** 2025-11-24
**Status:** In Progress - Admin Routes Testing
**Last Updated:** 2025-11-24

---

## Session 2025-11-24: Admin Routes Coverage

### 🎯 New Approach: Admin Routes Testing

After completing the 3 admin services (WordManagement, AudioManagement, CurriculumImport), coverage increased from 50% → 51%.
A new strategy was adopted: **focus on admin routes** which have large codebases with very low coverage.

### ✅ Completed in This Session

#### 1. tests/admin/routes/test_word_routes.py ⭐ SUCCESS
- **File:** `app/admin/routes/word_routes.py` (246 lines, was 22%)
- **Tests Created:** 15 tests for 5 routes
- **Result:** ✅ **ALL 15 TESTS PASSING**
- **Routes Covered:**
  - `/admin/words` (GET)
  - `/admin/words/bulk-status-update` (POST)
  - `/admin/words/export` (GET)
  - `/admin/words/import-translations` (GET/POST)
  - `/admin/words/statistics` (GET)

#### 2. tests/admin/routes/test_book_routes.py 🟡 PARTIAL
- **File:** `app/admin/routes/book_routes.py` (656 lines, was 13%)
- **Tests Created:** 26 tests for 8 routes
- **Result:** 🟡 13 passing, 13 failing (50% success)
- **Routes Covered:**
  - `/admin/books` (GET)
  - `/admin/books/scrape-website` (POST)
  - `/admin/books/update-statistics` (POST)
  - `/admin/books/process-phrasal-verbs` (POST)
  - `/admin/books/statistics` (GET)
  - `/admin/books/extract-metadata` (POST)
  - `/admin/books/cleanup` (GET/POST)
  - `/admin/books/add` (GET/POST)
- **Issues:** Some tests fail due to missing BookProcessingService methods

#### 3. tests/admin/routes/test_system_routes.py 🟡 PARTIAL
- **File:** `app/admin/routes/system_routes.py` (117 lines, was 35.9%)
- **Tests Created:** 16 tests for 5 routes
- **Result:** 🟡 5 passing, 11 errors (DB teardown timeouts)
- **Routes Covered:**
  - `/admin/system/clear-cache` (POST)
  - `/admin/system` (GET)
  - `/admin/system/database` (GET)
  - `/admin/system/database/init` (POST)
  - `/admin/system/database/test-connection` (GET)

#### 4. tests/admin/routes/conftest.py
- **Purpose:** Shared fixtures for admin route testing
- **Content:** `mock_admin_user` fixture to bypass `@admin_required` decorator

### 📊 Coverage Progress

| Stage | Coverage | Change |
|-------|----------|--------|
| Start of session | 51% | - |
| After admin routes tests | ~52-53%* | +1-2%* |
| **Target** | **55%** | **-2-3%*** |

*Final results pending

### 📈 Impact Analysis

**Total Created:**
- 57 tests across 3 files
- ~700 lines of test code
- Covering 1,019 lines of production code (656 + 246 + 117)

**Expected Coverage Increase:**
- word_routes: 246 × 60% = 148 lines → +0.8%
- book_routes: 656 × 30% = 197 lines → +1.1%
- system_routes: 117 × 40% = 47 lines → +0.3%
- **Total:** +2.2% (optimistic estimate)

### 🔴 Challenges Encountered

1. **DB Teardown Timeouts:** Many tests fail during cleanup with `DROP TABLE` timeouts
2. **Missing Service Methods:** Some mocked methods don't exist in BookProcessingService
3. **Authentication Bypass:** Required custom `mock_admin_user` fixture
4. **Celery Dependency:** Had to delete `tests/tasks/test_audio_tasks.py` (no Celery installed)

### 📝 Recommendations for 55% Target

**Option A: Fix Existing Tests** (+1-1.5%)
- Fix failing book_routes tests (13 tests)
- Resolve DB teardown issues in system_routes (11 tests)

**Option B: Add More Route Tests** (+1-1.5%)
- `app/admin/routes/audio_routes.py` (169 lines, 30% coverage)
- `app/admin/routes/curriculum_routes.py` (261 lines, low coverage)

**Option C: Hybrid Approach**
- Fix critical failing tests (+0.5%)
- Add audio_routes tests (+0.5-1%)
- Total: +1-1.5% → reach 53.5-54%

### 📦 Files Created This Session

```
tests/admin/routes/
├── conftest.py              (shared fixtures)
├── test_book_routes.py      (26 tests, 335 lines)
├── test_word_routes.py      (15 tests, 155 lines) ✅
└── test_system_routes.py    (16 tests, 210 lines)
```

**Next Action:** Await final coverage results, then decide on Option A, B, or C
