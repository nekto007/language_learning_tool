/**
 * SRS (Spaced Repetition System) integration functionality for the Language Learning Tool
 * Handles deck creation and word import for spaced repetition studies
 */

// Cache selected word IDs to avoid recursion
let cachedSelectedWordIds = [];
// Track if decks are already loaded to prevent redundant API calls
let decksAlreadyLoaded = false;

/**
 * Initialize SRS deck integration functionality with auto-loading
 */
function initSrsIntegration() {
    console.log("Initializing SRS integration");

    // Create new deck button
    document.getElementById('createNewDeckBtn')?.addEventListener('click', function (e) {
        e.preventDefault();
        showCreateDeckModal();
    });

    // Create deck with words button
    document.getElementById('createDeckWithWordsBtn')?.addEventListener('click', function (e) {
        e.preventDefault();
        createDeckWithWords();
    });

    // Import words to deck button
    document.getElementById('importWordsToDeckBtn')?.addEventListener('click', function (e) {
        e.preventDefault();
        importWordsToDeck();
    });

    // Add deck click handler for the dropdown menu items
    document.addEventListener('click', function (e) {
        const deckItem = e.target.closest('.deck-item');
        if (deckItem) {
            e.preventDefault();
            const deckId = deckItem.dataset.deckId;
            const deckName = deckItem.dataset.deckName;

            if (deckId && deckName) {
                showImportToDeckModal(deckId, deckName);
            }
        }
    });

    // Set up automatic deck loading when dropdown is opened
    const importToDeckDropdown = document.getElementById('importToDeckDropdown');
    if (importToDeckDropdown) {
        importToDeckDropdown.addEventListener('shown.bs.dropdown', function() {
            console.log("Dropdown opened, loading decks");
            // Always reload decks on dropdown open for freshness
            loadDecksForImport();
        });
    }

    // Cache selected words on initialization
    updateSelectedWordsCache();

    // Set up event listeners for status action items
    document.addEventListener('click', function(e) {
        const statusAction = e.target.closest('.status-action');
        if (statusAction) {
            handleStatusAction(e);
        }
    });

    // Make sure words don't disappear in "All words" filter
    fixAllWordsFilter();

    console.log("SRS integration initialized");
}

// Make sure we're properly setting up Bootstrap events
function setupBootstrapEvents() {
    console.log("Setting up Bootstrap dropdown events");

    // Get the dropdown element
    const dropdownElement = document.getElementById('importToDeckDropdown');

    if (!dropdownElement) {
        console.error("Dropdown element not found");
        return;
    }

    // Manual event handlers for all dropdown events to debug
    dropdownElement.addEventListener('show.bs.dropdown', function() {
        console.log("Dropdown 'show' event triggered");
    });

    dropdownElement.addEventListener('shown.bs.dropdown', function() {
        console.log("Dropdown 'shown' event triggered");
        // This is the most reliable place to trigger the loading
        loadDecksForImport();
    });

    dropdownElement.addEventListener('hide.bs.dropdown', function() {
        console.log("Dropdown 'hide' event triggered");
    });

    dropdownElement.addEventListener('hidden.bs.dropdown', function() {
        console.log("Dropdown 'hidden' event triggered");
    });

    // Also direct click handler as fallback
    dropdownElement.addEventListener('click', function() {
        console.log("Dropdown clicked");
        // Wait a very short time to ensure the dropdown has opened
        setTimeout(function() {
            if (dropdownElement.classList.contains('show')) {
                console.log("Dropdown appears to be open, loading decks");
                loadDecksForImport();
            }
        }, 50);
    });
}

// Add fallback options for decks selection
function ensureDeckOptionsAvailable() {
    console.log("Ensuring deck options are available");

    const select = document.getElementById('targetDeckSelect');
    if (select && select.options.length <= 1) {
        // Add main deck as a fallback
        const option = document.createElement('option');
        option.value = "1";  // Main deck is usually ID 1
        option.textContent = "Main Deck";
        select.appendChild(option);

        console.log("Added fallback Main Deck option");
    }

    const container = document.getElementById('existingDecksContainer');
    if (container && (container.children.length === 0 || container.querySelector('.spinner-border'))) {
        container.innerHTML = `
        <div class="py-1">
            <a href="#" class="deck-item text-decoration-none d-block" 
               data-deck-id="1" 
               data-deck-name="Main Deck">
               Main Deck
            </a>
        </div>`;
        console.log("Added fallback Main Deck to container");
    }
}

// Call this function after a short delay to ensure options are available
setTimeout(ensureDeckOptionsAvailable, 1000);

/**
 * Update the cache of selected word IDs
 */
function updateSelectedWordsCache() {
    // Get IDs directly from checkboxes to avoid recursion with wordSelection module
    const checkboxes = document.querySelectorAll('input.word-checkbox:checked');
    cachedSelectedWordIds = Array.from(checkboxes)
        .map(cb => parseInt(cb.value || cb.dataset.wordId || '0'))
        .filter(id => id > 0);
}

/**
 * Get selected word IDs safely
 * @returns {Array} Array of selected word IDs
 */
function getSelectedWordIds() {
    // Update cache first
    updateSelectedWordsCache();

    // Try the wordSelection module first if available
    if (window.wordSelection && typeof window.wordSelection.getSelectedWordIds === 'function') {
        return window.wordSelection.getSelectedWordIds();
    }

    // Fall back to cached IDs if no module available
    return cachedSelectedWordIds;
}

/**
 * Show the create deck modal
 */
function showCreateDeckModal() {
    // Get selected word IDs
    const selectedWordIds = getSelectedWordIds();

    if (selectedWordIds.length === 0) {
        // Only show toast for warnings, not for info text that's in the modal
        showToast('Please select at least one word to create a deck', 'warning', true);
        return;
    }

    // Update selected words count
    const countElement = document.getElementById('selectedWordsCount');
    if (countElement) {
        countElement.textContent = selectedWordIds.length;
    }

    // Clear form
    document.getElementById('createDeckForm')?.reset();

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('createDeckModal'));
    modal.show();
}

/**
 * Completely revamped deck loading functionality
 * This simplified version should work regardless of backend status changes
 */

// Replace the loadDecksForImport function with this improved version
async function loadDecksForImport() {
    const container = document.getElementById('existingDecksContainer');
    if (!container) return;

    // Show loading state
    container.innerHTML = '<div class="text-center py-2"><div class="spinner-border spinner-border-sm" role="status"></div> Loading...</div>';

    try {
        console.log("Starting deck load request");

        // Make the API request with a timeout
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000); // 8 second timeout

        const response = await fetch('/srs/api/decks', {
            signal: controller.signal,
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        clearTimeout(timeoutId);

        console.log("Response received:", response.status);

        // Check for HTTP errors
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }

        // Get response as text first for debugging
        const rawText = await response.text();
        console.log("Raw response (first 100 chars):", rawText.substring(0, 100));

        // Parse JSON (in try-catch to handle parsing errors)
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (e) {
            console.error("JSON parse error:", e);
            throw new Error("Invalid JSON from server");
        }

        console.log("Parsed data structure:", Object.keys(data));

        // Check data structure
        if (!data || !data.success || !Array.isArray(data.decks)) {
            console.error("Unexpected data structure:", data);
            throw new Error("Invalid data structure from server");
        }

        // Process the decks data
        const decks = data.decks;
        console.log(`Received ${decks.length} decks`);

        if (decks.length > 0) {
            // Update dropdown in modal window
            const select = document.getElementById('targetDeckSelect');
            if (select) {
                select.innerHTML = '<option value="" disabled selected>Choose a deck</option>';

                decks.forEach(deck => {
                    // Safety checks for the deck object
                    const deckId = deck.id || 0;
                    const deckName = deck.name || 'Unnamed Deck';
                    const cardCount = (deck.total_cards || deck.card_count || 0);

                    const option = document.createElement('option');
                    option.value = deckId;
                    option.textContent = `${deckName} (${cardCount} cards)`;
                    select.appendChild(option);
                });
            }

            // Build deck list for dropdown menu
            let decksHtml = '';
            decks.forEach(deck => {
                // Safety checks for the deck object
                const deckId = deck.id || 0;
                const deckName = deck.name || 'Unnamed Deck';
                const cardCount = (deck.total_cards || deck.card_count || 0);

                decksHtml += `
                <div class="py-1">
                    <a href="#" class="deck-item text-decoration-none d-block" 
                       data-deck-id="${deckId}" 
                       data-deck-name="${deckName}">
                       ${deckName} <small class="text-muted">(${cardCount})</small>
                    </a>
                </div>
                `;
            });

            container.innerHTML = decksHtml;
            console.log("Deck list updated successfully");

            // Mark decks as loaded
            window.decksAlreadyLoaded = true;
        } else {
            container.innerHTML = '<div class="text-center py-2 text-muted">No available decks</div>';
            console.log("No decks available");
        }
    } catch (error) {
        console.error('Error loading decks:', error);

        // Provide clear error message and retry button
        container.innerHTML = `
        <div class="text-center py-2">
            <div class="alert alert-danger py-2 small mb-0">
                ${error.message || 'Failed to load decks'}
            </div>
            <button class="btn btn-sm btn-outline-secondary mt-2" onclick="loadDecksForImport()">
                <i class="bi bi-arrow-repeat me-1"></i> Try Again
            </button>
        </div>`;

        // Reset loaded state so we try again next time
        window.decksAlreadyLoaded = false;
    }
}

/**
 * Show the import to deck modal
 * @param {string} deckId - Deck ID to import to
 * @param {string} deckName - Deck name for display
 */
function showImportToDeckModal(deckId, deckName) {
    // Get selected word IDs
    const selectedWordIds = getSelectedWordIds();

    if (selectedWordIds.length === 0) {
        // Only show toast for warnings, not for info text that's in the modal
        showToast('Please select at least one word to import', 'warning', true);
        return;
    }

    // Set selected deck in dropdown
    const select = document.getElementById('targetDeckSelect');
    if (select) {
        // Check if the option already exists
        let option = Array.from(select.options).find(opt => opt.value === deckId);

        // If not, create it
        if (!option) {
            option = document.createElement('option');
            option.value = deckId;
            option.textContent = deckName;
            select.appendChild(option);
        }

        // Select it
        select.value = deckId;
    }

    // Update modal title
    const modalTitle = document.getElementById('importToDeckModalLabel');
    if (modalTitle) {
        modalTitle.textContent = `Import to Deck: ${deckName}`;
    }

    // Update selected words count
    const countElement = document.getElementById('importWordsCount');
    if (countElement) {
        countElement.textContent = selectedWordIds.length;
    }

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('importToDeckModal'));
    modal.show();
}

/**
 * Update the UI to reflect the new status of words after deck operations
 * @param {Array} wordIds - Array of word IDs that were affected
 * @param {number} newStatus - The new status code
 */
function updateWordStatusInUI(wordIds, newStatus) {
    if (!wordIds || wordIds.length === 0 || newStatus === undefined) {
        return;
    }

    // Get status label for the new status
    let statusLabel = 'Unknown';
    if (window.statusLabels && window.statusLabels[newStatus] !== undefined) {
        statusLabel = window.statusLabels[newStatus];
    } else {
        // Fallback values if window.statusLabels is not available
        switch (newStatus) {
            case 0: statusLabel = 'New'; break;
            case 1: statusLabel = 'Studying'; break;
            case 2: statusLabel = 'Studied'; break;
        }
    }

    // Update each word row in the table
    wordIds.forEach(wordId => {
        const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
        if (!wordRow) return;

        // Find status badge in the row
        const statusBadge = wordRow.querySelector('.status-badge');
        if (statusBadge) {
            // Update badge classes
            statusBadge.className = `status-badge status-${newStatus}`;
            statusBadge.textContent = statusLabel;
        }

        // Update status dropdown in actions column if present
        const statusDropdownItems = wordRow.querySelectorAll('.status-action');
        statusDropdownItems.forEach(item => {
            const itemStatus = parseInt(item.dataset.status);
            if (itemStatus === newStatus) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    });

    // Update status count displays if they exist
    updateStatusCountsInUI();
}

/**
 * Update status count displays in the UI
 */
function updateStatusCountsInUI() {
    // Get all visible words by status
    const statusCounts = {};
    let totalVisible = 0;

    // Count words by status
    document.querySelectorAll('.word-row').forEach(row => {
        // Check if the row is visible (not filtered out)
        const isDisplayed = window.getComputedStyle(row).display !== 'none';
        if (!isDisplayed) return;

        totalVisible++;

        const statusBadge = row.querySelector('.status-badge');
        if (statusBadge) {
            // Extract status number from class name
            const statusClasses = Array.from(statusBadge.classList)
                .find(cls => cls.startsWith('status-') && cls !== 'status-badge');

            if (statusClasses) {
                const status = statusClasses.replace('/status-/', '');
                statusCounts[status] = (statusCounts[status] || 0) + 1;
            }
        }
    });

    // Update status tab counts if they exist
    document.querySelectorAll('.status-tab').forEach(tab => {
        const countSpan = tab.querySelector('.status-count');
        if (!countSpan) return;

        const tabClasses = Array.from(tab.classList)
            .find(cls => cls.startsWith('status-tab-'));

        if (tabClasses) {
            const status = tabClasses.replace('status-tab-', '');
            countSpan.textContent = statusCounts[status] || 0;
        } else if (tab.classList.contains('active') && !tabClasses) {
            // This is likely the "All" tab
            countSpan.textContent = totalVisible;
        }
    });
}

/**
 * Fix for the "All Words" filter to ensure all words are displayed regardless of status
 * This should be added to your srs-integration.js file
 */

/**
 * Apply the "All Words" filter fix when the page loads and after any status changes
 */
function fixAllWordsFilter() {
    // Check if we're in the "All words" filter
    const isAllWordsView = document.querySelector('.status-tab.active:not([class*="status-tab-"])') !== null;

    if (isAllWordsView) {
        console.log("All Words filter is active - ensuring all words are visible");

        // Make all word rows visible
        document.querySelectorAll('.word-row').forEach(row => {
            // Remove any style that might be hiding it
            row.style.display = '';

            // Also remove any classes that might be hiding it
            if (row.classList.contains('d-none')) {
                row.classList.remove('d-none');
            }

            // Check if the row is still hidden after our changes
            const isHidden = window.getComputedStyle(row).display === 'none';
            if (isHidden) {
                console.log(`Row for word ID ${row.dataset.wordId} is still hidden, forcing display`);
                row.style.display = 'table-row'; // Force display as table row
            }
        });

        // Look for any CSS that might be hiding rows
        const styles = document.styleSheets;
        let problematicRules = [];

        try {
            // Check for problematic CSS rules
            for (let i = 0; i < styles.length; i++) {
                try {
                    const rules = styles[i].cssRules || styles[i].rules;
                    if (!rules) continue;

                    for (let j = 0; j < rules.length; j++) {
                        const rule = rules[j];
                        const selector = rule.selectorText || '';

                        // Look for rules that might hide word rows
                        if (selector.includes('.word-row') &&
                            (rule.style.display === 'none' || rule.style.visibility === 'hidden')) {
                            problematicRules.push(selector);
                        }
                    }
                } catch (e) {
                    // Some stylesheets might not be accessible due to CORS
                    continue;
                }
            }

            if (problematicRules.length > 0) {
                console.log("Found CSS rules that might be hiding words:", problematicRules);

                // Add an override style to counteract these rules
                const style = document.createElement('style');
                style.textContent = `
                    /* Override to fix All Words filter */
                    .status-tab.active:not([class*="status-tab-"]) ~ .card-body .word-row {
                        display: table-row !important;
                        visibility: visible !important;
                    }
                `;
                document.head.appendChild(style);
            }
        } catch (e) {
            console.error("Error analyzing CSS:", e);
        }
    }
}

/**
 * Observer to detect DOM changes and reapply the filter fix when needed
 */
function setupFilterObserver() {
    // Get the element that contains words
    const wordsContainer = document.querySelector('.words-table tbody');

    if (wordsContainer) {
        // Create a MutationObserver to watch for changes
        const observer = new MutationObserver((mutations) => {
            fixAllWordsFilter();
        });

        // Start observing
        observer.observe(wordsContainer, {
            childList: true,  // Watch for added/removed nodes
            subtree: true,    // Watch the entire subtree
            attributes: true  // Watch for attribute changes that might show/hide elements
        });

        console.log("Filter observer set up to monitor word visibility");
    }

    // Also observe tab changes
    const statusTabs = document.querySelector('.status-tabs');
    if (statusTabs) {
        statusTabs.addEventListener('click', (e) => {
            // Wait a moment for the UI to update
            setTimeout(fixAllWordsFilter, 100);
        });
    }
}

/**
 * Event handler for status action items
 * Improved to update UI directly after status change
 */
function handleStatusAction(e) {
    e.preventDefault();

    const element = e.target.closest('.status-action');
    if (!element) return;

    const wordId = parseInt(element.dataset.wordId);
    const status = parseInt(element.dataset.status);

    if (isNaN(wordId) || isNaN(status)) return;

    // Update status via API
    updateWordStatus(wordId, status)
        .then(response => {
            if (response.success) {
                // Update UI directly without page reload
                updateWordStatusInUI([wordId], status);
            } else {
                showToast(response.message || 'Error updating status', 'danger');
            }
        })
        .catch(error => {
            console.error('Error updating word status:', error);
            showToast('Error updating status', 'danger');
        });
}

/**
 * Update word status via API
 * @param {number} wordId - Word ID
 * @param {number} status - New status code
 * @returns {Promise} - Promise resolving to API response
 */
async function updateWordStatus(wordId, status) {
    try {
        const response = await fetch('/api/update_word_status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                wordId: wordId,
                status: status
            })
        });

        return await response.json();
    } catch (error) {
        console.error('API error:', error);
        return { success: false, message: 'API request failed' };
    }
}

/**
 * Create a new deck with selected words with improved status handling
 */
async function createDeckWithWords() {
    // Get selected word IDs
    const selectedWordIds = getSelectedWordIds();

    if (selectedWordIds.length === 0) {
        showToast('Please select at least one word', 'warning');
        return;
    }

    // Get deck name and description
    const deckName = document.getElementById('deckNameInput')?.value.trim();
    const description = document.getElementById('deckDescriptionInput')?.value.trim();

    if (!deckName) {
        showToast('Please enter a deck name', 'warning');
        return;
    }

    // Update button state
    const button = document.getElementById('createDeckWithWordsBtn');
    if (!button) return;

    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Creating...';

    try {
        // Fixed URL to match Flask routes
        const response = await fetch('/srs/api/import/deck', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                deckName: deckName,
                description: description,
                wordIds: selectedWordIds
            }),
        });

        const data = await response.json();

        if (data.success) {
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('createDeckModal'));
            if (modal) {
                modal.hide();
            }

            // Show success message
            showToast(`Deck "${deckName}" successfully created. Added ${data.addedCount} of ${data.totalCount} words.`, 'success');

            // Update UI to reflect status changes (assuming words change to Active status)
            updateWordStatusInUI(selectedWordIds, 1); // 1 = Active status

            // Reset form
            document.getElementById('createDeckForm')?.reset();

            // Clear selection if configured
            if (data.clearSelection) {
                clearWordSelection();
            }

            // Reset deck cache to force reload next time
            decksAlreadyLoaded = false;
        } else {
            showToast(`Error: ${data.error || 'Failed to create deck'}`, 'danger');
        }
    } catch (error) {
        console.error('Error creating deck:', error);
        showToast('Error when creating deck', 'danger');
    } finally {
        // Restore button
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

/**
 * Import selected words to an existing deck with improved status handling
 */
async function importWordsToDeck() {
    // Get selected word IDs
    const selectedWordIds = getSelectedWordIds();

    if (selectedWordIds.length === 0) {
        showToast('Please select at least one word', 'warning');
        return;
    }

    // Get selected deck
    const select = document.getElementById('targetDeckSelect');
    if (!select || !select.value) {
        showToast('Please select a deck for import', 'warning');
        return;
    }

    const deckId = select.value;
    const deckName = select.options[select.selectedIndex].text;

    // Update button state
    const button = document.getElementById('importWordsToDeckBtn');
    if (!button) return;

    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Importing...';

    try {
        // Fixed URL to match Flask routes
        const response = await fetch('/srs/api/import/words', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                deckId: deckId,
                wordIds: selectedWordIds
            }),
        });

        const data = await response.json();

        if (data.success) {
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('importToDeckModal'));
            if (modal) {
                modal.hide();
            }

            // Show success message
            showToast(`Words imported to deck "${deckName}". Added: ${data.addedCount}, Skipped: ${data.skippedCount}, Total: ${data.totalCount}`, 'success');

            // Update UI to reflect status changes (to STUDYING status)
            updateWordStatusInUI(selectedWordIds, 1); // 1 = STUDYING status (new value)

            // Clear selection if configured
            if (data.clearSelection) {
                clearWordSelection();
            }
        } else {
            showToast(`Error: ${data.error || 'Failed to import words'}`, 'danger');
        }
    } catch (error) {
        console.error('Error importing words:', error);
        showToast('Error when importing words', 'danger');
    } finally {
        // Restore button
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

/**
 * Clear word selection
 */
function clearWordSelection() {
    // Uncheck all checkboxes
    document.querySelectorAll('.word-checkbox, #selectAll').forEach(cb => {
        cb.checked = false;
    });

    // Reset cached IDs
    cachedSelectedWordIds = [];

    // Also update the module if available (but avoid direct recursion)
    if (window.wordSelection) {
        // Reset the array directly without calling functions that could recurse
        window.wordSelection.selectedWordIds = [];

        // If updateAllSelectionCounters exists and is a function, call it
        if (typeof window.wordSelection.updateAllSelectionCounters === 'function') {
            window.wordSelection.updateAllSelectionCounters();
        }
    }

    // Update counters directly as fallback
    updateCountersDirectly();
}

/**
 * Update counters directly without using the wordSelection module
 */
function updateCountersDirectly() {
    const count = 0; // Since we're clearing selection, count is always 0

    // Update main counter
    const selectedCountDisplay = document.getElementById('selectedCount');
    if (selectedCountDisplay) {
        selectedCountDisplay.textContent = `${count} selected`;
    }

    // Update Anki counter
    const ankiCountElem = document.getElementById('ankiSelectedWordsCount');
    if (ankiCountElem) {
        ankiCountElem.textContent = `Selected words: ${count}`;
    }

    // Update SRS deck counters
    const deckWordsCount = document.getElementById('selectedWordsCount');
    if (deckWordsCount) {
        deckWordsCount.textContent = count;
    }

    const importWordsCount = document.getElementById('importWordsCount');
    if (importWordsCount) {
        importWordsCount.textContent = count;
    }

    // Disable buttons if needed
    const createBtn = document.getElementById('createDeckWithWordsBtn');
    const importBtn = document.getElementById('importWordsToDeckBtn');

    if (createBtn) {
        createBtn.disabled = count === 0;
    }

    if (importBtn) {
        importBtn.disabled = count === 0;
    }
}

/**
 * Synchronize word status with improved error handling and fallback
 */
async function syncWordStatus() {
    try {
        // Show notification about sync start
        showToast('Syncing word status...', 'info', true);

        // Send request to API for synchronization
        const response = await fetch('/srs/api/sync/word_status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin', // Include cookies for session authentication
            body: JSON.stringify({}) // Empty JSON object - this is crucial!
        });

        if (!response.ok) {
            // Try to get more detailed error information
            let errorDetails = "";
            try {
                const errorText = await response.text();
                errorDetails = errorText;
            } catch (e) {
                // Ignore text parsing errors
            }

            throw new Error(`Server returned ${response.status}: ${response.statusText}. ${errorDetails}`);
        }

        const data = await response.json();

        if (data.success) {
            showToast(`${data.message}`, 'success', true);

            // If words were updated, refresh the page to show changes
            if (data.updated_count > 0) {
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }
        } else {
            showToast(`Error: ${data.error || 'Failed to sync word status'}`, 'danger', true);
        }
    } catch (error) {
        console.error('Error syncing word status:', error);
        showToast('Error syncing word status. Try refreshing the page.', 'danger', true);
    }
}

/**
 * Show a toast notification without recursion issues
 * @param {string} message - Message to display
 * @param {string} type - Bootstrap color type (success, danger, warning, info)
 * @param {boolean} logToConsole - Whether to log to console
 */
function showToast(message, type = 'info', logToConsole = false) {
    // Check if the message is one of our info texts from modals - if so, don't display it as a toast
    if (type === 'info' && (
        message.includes('A new deck will be created with') ||
        message.includes('Selected words') && message.includes('will be added to the specified deck')
    )) {
        // Just log it if requested, but don't show toast
        if (logToConsole) {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
        return;
    }

    // CRITICAL FIX: Prevent recursion by checking if we're in the middle of showing a toast
    if (window._showingToast) {
        console.warn("Avoiding recursive showToast call:", message);
        return;
    }

    // Set a flag to prevent recursion
    window._showingToast = true;

    try {
        // Only log to console for errors, warnings, or if explicitly requested
        if (logToConsole || type === 'danger' || type === 'warning') {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }

        // Create main toast container if it doesn't exist
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(toastContainer);
        }

        // Create notification
        const toastId = 'toast-' + Date.now();
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type} border-0`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.setAttribute('id', toastId);

        toast.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">
            ${message}
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" 
                  data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      `;

        // Add to container
        toastContainer.appendChild(toast);

        // Initialize and show toast
        if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
            const bsToast = new bootstrap.Toast(toast, {
                delay: 3000,
                autohide: true
            });

            bsToast.show();

            // Remove from DOM after hiding
            toast.addEventListener('hidden.bs.toast', function () {
                toast.remove();
            });
        } else {
            // Fallback implementation if bootstrap is unavailable
            toast.style.opacity = '1';
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s';
                setTimeout(() => toast.remove(), 500);
            }, 3000);
        }
    } finally {
        // Always clear the flag when done, even if there's an error
        window._showingToast = false;
    }
}

// Set a global flag to identify this is our implementation
window.showToastImplemented = true;

// Marker to distinguish local function from global one
// Add only if another function hasn't set this
if (typeof window.showToastOrigin === 'undefined') {
    window.showToastOrigin = 'srs-integration.js';
}

/**
 * Enhanced SRS integration - with Sync Word Status moved to Bulk Actions
 */
function enhanceSrsIntegration() {
    // Find the import dropdown menu
    const importDropdownMenu = document.querySelector('[aria-labelledby="importToDeckDropdown"]');
    if (importDropdownMenu) {
        // Remove Load Decks List button
        const loadDecksItem = document.getElementById('loadDecksForImportBtn')?.closest('li');
        if (loadDecksItem) {
            loadDecksItem.remove();
        }
    }

    // Find the bulk actions dropdown menu
    const bulkActionsMenu = document.querySelector('[aria-labelledby="bulkActionsBtn"]');
    if (bulkActionsMenu) {
        // Find the divider after status options
        const divider = bulkActionsMenu.querySelector('.dropdown-divider');

        if (divider) {
            // Create element for sync button
            const syncOption = document.createElement('li');
            syncOption.innerHTML = `<a class="dropdown-item" href="#" id="syncWordStatusBtn">
                <i class="bi bi-arrow-repeat me-1"></i> Sync Word Status
            </a>`;

            // Insert before the "Create Anki Cards" option if it exists,
            // or after the divider if not
            const ankiOption = bulkActionsMenu.querySelector('#createAnkiBtn')?.closest('li');
            if (ankiOption) {
                bulkActionsMenu.insertBefore(syncOption, ankiOption);
            } else {
                bulkActionsMenu.appendChild(syncOption);
            }

            // Add event handler for sync button
            document.getElementById('syncWordStatusBtn')?.addEventListener('click', function(e) {
                e.preventDefault();
                syncWordStatus();
            });
        }
    }
}

/**
 * Improved play pronunciation function
 * Replace your existing implementation with this code
 */

// Add this function to your JavaScript file
function playPronunciation(word) {
    // Log for debugging
    console.log("Attempting to play pronunciation for:", word);

    if (!word) {
        console.error("No word provided for pronunciation");
        return;
    }

    // Format the word for the filename (lowercase, replace spaces with underscores)
    const formattedWord = word.toLowerCase().replace(/\s+/g, '_');

    // Create audio element if it doesn't exist
    let audioElement = document.getElementById('pronunciation-audio');
    if (!audioElement) {
        audioElement = document.createElement('audio');
        audioElement.id = 'pronunciation-audio';
        document.body.appendChild(audioElement);
    }

    // Set up error handling
    audioElement.onerror = function(e) {
        console.error("Error playing pronunciation:", e);
        showToast("Couldn't play pronunciation. Audio file may not exist.", "warning");
    };

    // Set up success handling
    audioElement.onplay = function() {
        console.log("Pronunciation playing successfully");
    };

    // Set the source - try multiple possible paths
    const possiblePaths = [
        `/static/media/pronunciation_en_${formattedWord}.mp3`,
        `/static/media/${formattedWord}.mp3`,
        `/static/audio/pronunciation_en_${formattedWord}.mp3`,
        `/static/audio/${formattedWord}.mp3`
    ];

    // Try to preload the audio from different possible paths
    let loaded = false;

    function tryNextPath(index) {
        if (index >= possiblePaths.length) {
            if (!loaded) {
                console.error("Failed to load pronunciation from any path");
                showToast("Pronunciation not available", "warning");
            }
            return;
        }

        const path = possiblePaths[index];
        console.log(`Trying path: ${path}`);

        // Create a temporary audio element to test if the file exists
        const testAudio = new Audio();

        testAudio.oncanplay = function() {
            console.log(`Successfully loaded audio from: ${path}`);
            // Use the working path
            audioElement.src = path;
            audioElement.play().catch(e => {
                console.error("Error playing audio:", e);
            });
            loaded = true;
        };

        testAudio.onerror = function() {
            console.log(`Failed to load audio from: ${path}`);
            // Try the next path
            tryNextPath(index + 1);
        };

        // Try to load this path
        testAudio.src = path;
    }

    // Start trying paths
    tryNextPath(0);
}

// Initialize filter fixes when the document loads
document.addEventListener('DOMContentLoaded', function() {
    // Add a global click handler for all pronunciation buttons
    document.addEventListener('click', function(event) {
        // Check if clicked element is a pronunciation button or its child icon
        const button = event.target.closest('.play-pronunciation');
        if (!button) return;

        // Prevent default behavior (important for buttons inside forms)
        event.preventDefault();

        // Get the word from the data attribute
        const word = button.dataset.word;

        if (word) {
            playPronunciation(word);
        } else {
            console.error("No word data attribute found on pronunciation button");
        }
    });

    console.log("Pronunciation event handlers initialized");
});

// Export functions for use in other modules
window.srsIntegration = {
    showCreateDeckModal,
    loadDecksForImport,
    importWordsToDeck,
    createDeckWithWords,
    clearWordSelection,
    updateWordStatusInUI
};