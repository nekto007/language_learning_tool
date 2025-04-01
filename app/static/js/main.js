document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM loaded, initializing enhanced functionality");

    // Фикс: Проверяем наличие структуры таблицы
    const table = document.querySelector('table');
    if (table) {
        // Страница со списком слов - нужно убедиться, что всё правильно настроено
        setupTable();
    }

    // Initialize Bootstrap tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltipTriggerList.length > 0) {
        tooltipTriggerList.forEach(function (tooltipTriggerEl) {
            new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Delayed flash message dismissal
    const alertList = document.querySelectorAll('.alert:not(.alert-permanent)');
    alertList.forEach(function(alert) {
        setTimeout(function() {
            try {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } catch (e) {
                console.warn("Error closing alert:", e);
            }
        }, 5000);
    });

    // Audio pronunciation player
    setupAudioPronunciation();

    // Determine which page we're on and call the appropriate setup function
    if (document.querySelector('.word-list-page') ||
        document.querySelectorAll('.word-checkbox').length > 0) {
        setupWordListPage();
        // Initialize the enhanced bulk actions functionality
        enhancedBulkActionsSetup();
    } else if (document.querySelector('.word-detail-page')) {
        setupWordDetailPage();
    } else if (document.querySelector('.dashboard-page')) {
        setupDashboardPage();
    } else if (document.querySelector('.book-list-page')) {
        setupBookListPage();
    } else if (document.querySelector('.book-detail-page')) {
        setupBookDetailPage();
    }
});

// Enhanced bulk actions functionality
function enhancedBulkActionsSetup() {
    try {
        // Get all necessary elements
        const selectAllCheckbox = document.getElementById('selectAll');
        const wordCheckboxes = document.querySelectorAll('.word-checkbox');
        const bulkActionsDropdown = document.getElementById('bulkActionsDropdown');
        const bulkActionButtons = document.querySelectorAll('.bulk-action');
        const bulkExportBtn = document.getElementById('bulkExportBtn');

        console.log(`Setting up enhanced bulk actions with ${wordCheckboxes.length} checkboxes`);

        if (!selectAllCheckbox || wordCheckboxes.length === 0) {
            console.warn("Required elements for bulk actions not found, skipping setup");
            return;
        }

        // Remove any existing event listeners by cloning elements
        if (selectAllCheckbox) {
            const newSelectAllCheckbox = selectAllCheckbox.cloneNode(true);
            if (selectAllCheckbox.parentNode) {
                selectAllCheckbox.parentNode.replaceChild(newSelectAllCheckbox, selectAllCheckbox);
            }

            // Add the change event listener to the new element
            newSelectAllCheckbox.addEventListener('change', function() {
                console.log("Select All checkbox clicked, new state:", this.checked);

                // Update all word checkboxes
                wordCheckboxes.forEach(checkbox => {
                    checkbox.checked = this.checked;
                });

                // Update the visual state of bulk action buttons
                updateBulkActionsVisualState();

                console.log("Word checkboxes updated, bulk actions state updated");
            });
        }

        // Add event listeners to word checkboxes
        wordCheckboxes.forEach(checkbox => {
            const newCheckbox = checkbox.cloneNode(true);
            if (checkbox.parentNode) {
                checkbox.parentNode.replaceChild(newCheckbox, checkbox);
            }

            newCheckbox.addEventListener('change', function() {
                console.log("Individual checkbox changed");

                // Update Select All checkbox state
                if (selectAllCheckbox) {
                    const totalCheckboxes = document.querySelectorAll('.word-checkbox').length;
                    const checkedCheckboxes = document.querySelectorAll('.word-checkbox:checked').length;

                    selectAllCheckbox.checked = (checkedCheckboxes === totalCheckboxes && totalCheckboxes > 0);
                    selectAllCheckbox.indeterminate = (checkedCheckboxes > 0 && checkedCheckboxes < totalCheckboxes);
                }

                // Update bulk actions
                updateBulkActionsVisualState();
            });
        });

        // Make sure click events on bulk action buttons work correctly
        bulkActionButtons.forEach(button => {
            // Remove existing click handlers to avoid duplicates
            const newButton = button.cloneNode(true);
            if (button.parentNode) {
                button.parentNode.replaceChild(newButton, button);
            }

            newButton.addEventListener('click', function(e) {
                e.preventDefault();

                const selectedIds = getSelectedWordIds();
                if (selectedIds.length === 0) {
                    alert('Please select at least one word first.');
                    return;
                }

                const status = this.dataset.status;
                console.log(`Bulk action clicked with status ${status} for ${selectedIds.length} words`);

                // Show loading indicator immediately
                showAlert(`Processing ${selectedIds.length} words...`, 'info');

                // Set a timeout to reload the page even if the fetch operation fails
                const fallbackTimer = setTimeout(() => {
                    console.log("Fallback timer triggered - reloading page");
                    showAlert("Operation likely succeeded, but communication with server timed out. Reloading page...", 'warning');
                    window.location.reload();
                }, 8000); // 8 seconds fallback

                // Perform the batch update with improved error handling
                fetch('/api/batch-update-status', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        word_ids: selectedIds,
                        status: parseInt(status)
                    })
                })
                .then(response => {
                    // Clear the fallback timer since we got a response
                    clearTimeout(fallbackTimer);

                    // Check if the response is ok (status 200-299)
                    if (!response.ok) {
                        console.warn(`Server responded with status: ${response.status}`);
                        // Even if status is not OK, the operation might have succeeded
                        showAlert("Server returned an error, but operation may have succeeded. Reloading...", 'warning');
                        setTimeout(() => window.location.reload(), 1500);
                        throw new Error(`Server responded with status: ${response.status}`);
                    }

                    // Try to parse the JSON response
                    return response.json();
                })
                .then(data => {
                    // Clear the fallback timer again just to be safe
                    clearTimeout(fallbackTimer);

                    if (data.success) {
                        // Show success message and reload
                        console.log("Bulk action successful, reloading page");
                        showAlert(`Successfully updated ${data.updated_count || selectedIds.length} word(s).`, 'success');
                        setTimeout(() => window.location.reload(), 1500);
                    } else {
                        alert(`Error: ${data.error || 'Unknown error'}`);
                        // Even with an error message, the operation might have succeeded
                        setTimeout(() => window.location.reload(), 3000);
                    }
                })
                .catch(error => {
                    // Clear the fallback timer if we reach this catch block
                    clearTimeout(fallbackTimer);

                    console.error('Error performing bulk action:', error);

                    // Show a message that explains the situation
                    showAlert('Communication error occurred, but your change may have been applied. Reloading page to check...', 'warning');

                    // Reload the page after a short delay to see if changes were applied
                    setTimeout(() => window.location.reload(), 2000);
                });
            });
        });

        // Initial update of button states
        updateBulkActionsVisualState();
        console.log("Enhanced bulk actions setup complete");
    } catch (e) {
        console.error("Error in enhanced bulk actions setup:", e);
    }
}

// This function handles the visual state of bulk action buttons and dropdowns
function updateBulkActionsVisualState() {
    try {
        // Get all required elements
        const bulkActionsDropdown = document.getElementById('bulkActionsDropdown');
        const bulkActionButtons = document.querySelectorAll('.bulk-action');
        const bulkExportBtn = document.getElementById('bulkExportBtn');

        // Count selected checkboxes
        const checkedCount = document.querySelectorAll('.word-checkbox:checked').length;
        console.log(`Updating bulk actions visual state: ${checkedCount} items selected`);

        // Determine if actions should be enabled
        const isEnabled = checkedCount > 0;

        // Update dropdown button (multiple approaches for compatibility)
        if (bulkActionsDropdown) {
            if (isEnabled) {
                bulkActionsDropdown.classList.remove('disabled');
                bulkActionsDropdown.removeAttribute('disabled');
                bulkActionsDropdown.removeAttribute('aria-disabled');
                bulkActionsDropdown.style.pointerEvents = '';
            } else {
                bulkActionsDropdown.classList.add('disabled');
                bulkActionsDropdown.setAttribute('disabled', 'disabled');
                bulkActionsDropdown.setAttribute('aria-disabled', 'true');
                bulkActionsDropdown.style.pointerEvents = 'none';
            }
        }

        // Update dropdown items
        bulkActionButtons.forEach(button => {
            if (isEnabled) {
                button.classList.remove('disabled');
                button.removeAttribute('disabled');
                button.removeAttribute('aria-disabled');
                button.style.pointerEvents = '';
            } else {
                button.classList.add('disabled');
                button.setAttribute('disabled', 'disabled');
                button.setAttribute('aria-disabled', 'true');
                button.style.pointerEvents = 'none';
            }
        });

        // Update export button
        if (bulkExportBtn) {
            bulkExportBtn.disabled = !isEnabled;
            if (isEnabled) {
                bulkExportBtn.classList.remove('disabled');
            } else {
                bulkExportBtn.classList.add('disabled');
            }
        }

        console.log(`Bulk actions are now ${isEnabled ? 'enabled' : 'disabled'}`);
    } catch (e) {
        console.error("Error updating bulk actions visual state:", e);
    }
}

// Улучшенная функция для настройки таблицы
function setupTable() {
    try {
        // Проверяем наличие индивидуальных чекбоксов для слов
        const wordCheckboxes = document.querySelectorAll('.word-checkbox');
        if (wordCheckboxes.length === 0) return; // Нет чекбоксов, нечего настраивать

        // Проверяем наличие чекбокса "выбрать всё"
        let selectAllCheckbox = document.getElementById('selectAll');

        if (!selectAllCheckbox) {
            console.log("Чекбокс selectAll не найден, добавляем его");

            // Ищем первую ячейку заголовка таблицы
            const firstHeaderCell = document.querySelector('table thead tr th:first-child');

            if (firstHeaderCell) {
                // Ищем внутри неё контейнер form-check или создаём новый
                let formCheckDiv = firstHeaderCell.querySelector('.form-check');

                if (!formCheckDiv) {
                    formCheckDiv = document.createElement('div');
                    formCheckDiv.className = 'form-check';
                    firstHeaderCell.appendChild(formCheckDiv);
                }

                // Создаём чекбокс
                selectAllCheckbox = document.createElement('input');
                selectAllCheckbox.type = 'checkbox';
                selectAllCheckbox.id = 'selectAll';
                selectAllCheckbox.className = 'form-check-input';

                // Добавляем его в контейнер
                formCheckDiv.appendChild(selectAllCheckbox);

                console.log("Добавлен чекбокс selectAll");
            } else {
                console.log("Не найдена первая ячейка заголовка таблицы");
            }
        }

        // Настройка чекбоксов будет выполнена в enhancedBulkActionsSetup
    } catch (e) {
        console.error("Ошибка при настройке таблицы:", e);
    }
}

function setupAudioPronunciation() {
    try {
        const pronunciationButtons = document.querySelectorAll('.pronunciation-button');

        pronunciationButtons.forEach(button => {
            button.addEventListener('click', function() {
                const audioId = this.dataset.audioTarget;
                const audioElement = document.getElementById(audioId);

                if (audioElement) {
                    audioElement.play();

                    // Visual feedback
                    this.classList.add('playing');

                    audioElement.onended = () => {
                        this.classList.remove('playing');
                    };
                }
            });
        });
    } catch (e) {
        console.warn("Error setting up audio pronunciation:", e);
    }
}

function setupWordListPage() {
    try {
        // Most functionality has been moved to enhancedBulkActionsSetup
        // This function now only handles non-checkbox related features

        // Export form submission
        const exportSubmitBtn = document.getElementById('exportSubmitBtn');
        if (exportSubmitBtn) {
            exportSubmitBtn.addEventListener('click', function() {
                const selectedIds = getSelectedWordIds();
                const formData = getExportFormData();

                if (!formData.deckName) {
                    showAlert('Please enter a deck name.', 'warning');
                    return;
                }

                // Prepare data for API
                const exportData = {
                    deckName: formData.deckName,
                    cardFormat: formData.cardFormat,
                    includePronunciation: formData.includePronunciation,
                    includeExamples: formData.includeExamples,
                    updateStatus: formData.updateStatus,
                    wordIds: selectedIds
                };

                try {
                    // Set up form for file download
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '/api/export-anki';

                    // Using a hidden iframe for file download
                    const downloadFrame = document.createElement('iframe');
                    downloadFrame.name = 'download_frame';
                    downloadFrame.style.display = 'none';
                    document.body.appendChild(downloadFrame);

                    form.target = 'download_frame';
                    form.style.display = 'none';

                    // Add data as JSON
                    const dataInput = document.createElement('input');
                    dataInput.type = 'hidden';
                    dataInput.name = 'data';
                    dataInput.value = JSON.stringify(exportData);
                    form.appendChild(dataInput);

                    // Submit form
                    document.body.appendChild(form);
                    form.submit();

                    // Close modal
                    const exportModal = document.getElementById('exportModal');
                    if (exportModal) {
                        const modal = bootstrap.Modal.getInstance(exportModal);
                        if (modal) {
                            modal.hide();
                        }
                    }

                    // Show confirmation
                    showAlert('Export initiated. The file will download shortly.', 'success');

                    // If updateStatus is true, reload after a delay
                    if (formData.updateStatus) {
                        setTimeout(() => {
                            window.location.reload();
                        }, 3000);
                    }
                } catch (e) {
                    console.error("Error during export:", e);
                    showAlert('An error occurred during export.', 'danger');
                }
            });
        }
    } catch (e) {
        console.error("Error setting up word list page:", e);
    }
}

function setupWordDetailPage() {
    try {
        // Export form for single word
        const singleExportBtn = document.getElementById('singleExportBtn');
        if (singleExportBtn) {
            singleExportBtn.addEventListener('click', function() {
                const wordId = this.dataset.wordId;
                const formData = getExportFormData();

                if (!formData.deckName) {
                    showAlert('Please enter a deck name.', 'warning');
                    return;
                }

                // Prepare data for API
                const exportData = {
                    deckName: formData.deckName,
                    cardFormat: formData.cardFormat,
                    includePronunciation: formData.includePronunciation,
                    includeExamples: formData.includeExamples,
                    updateStatus: formData.updateStatus,
                    wordIds: [parseInt(wordId)]
                };

                try {
                    // Set up form for file download
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '/api/export-anki';

                    // Using a hidden iframe for file download
                    const downloadFrame = document.createElement('iframe');
                    downloadFrame.name = 'download_frame';
                    downloadFrame.style.display = 'none';
                    document.body.appendChild(downloadFrame);

                    form.target = 'download_frame';
                    form.style.display = 'none';

                    // Add data as JSON
                    const dataInput = document.createElement('input');
                    dataInput.type = 'hidden';
                    dataInput.name = 'data';
                    dataInput.value = JSON.stringify(exportData);
                    form.appendChild(dataInput);

                    // Submit form
                    document.body.appendChild(form);
                    form.submit();

                    // Close modal
                    const exportModal = document.getElementById('exportModal');
                    if (exportModal) {
                        const modal = bootstrap.Modal.getInstance(exportModal);
                        if (modal) {
                            modal.hide();
                        }
                    }

                    // Show confirmation
                    showAlert('Export initiated. The file will download shortly.', 'success');

                    // If updateStatus is true, reload after a delay
                    if (formData.updateStatus) {
                        setTimeout(() => {
                            window.location.reload();
                        }, 3000);
                    }
                } catch (e) {
                    console.error("Error during export:", e);
                    showAlert('An error occurred during export.', 'danger');
                }
            });
        }
    } catch (e) {
        console.error("Error setting up word detail page:", e);
    }
}

function setupDashboardPage() {
    try {
        // Any dashboard-specific functionality
        const statsCards = document.querySelectorAll('.stat-card');

        statsCards.forEach(card => {
            card.addEventListener('mouseenter', function() {
                this.classList.add('shadow');
            });

            card.addEventListener('mouseleave', function() {
                this.classList.remove('shadow');
            });
        });
    } catch (e) {
        console.error("Error setting up dashboard page:", e);
    }
}

// Empty placeholder functions to prevent errors when they're called but not defined
function setupBookListPage() {
    // To be implemented
    console.log("Book list page setup placeholder");
}

function setupBookDetailPage() {
    // To be implemented
    console.log("Book detail page setup placeholder");
}

// Helper functions
function getSelectedWordIds() {
    try {
        const checkboxes = document.querySelectorAll('.word-checkbox:checked');
        return Array.from(checkboxes).map(checkbox => parseInt(checkbox.value));
    } catch (e) {
        console.error("Error getting selected word IDs:", e);
        return [];
    }
}

function updateSelectAllState() {
    try {
        const selectAllCheckbox = document.getElementById('selectAll');
        if (!selectAllCheckbox) return;

        const wordCheckboxes = document.querySelectorAll('.word-checkbox');
        if (wordCheckboxes.length === 0) return;

        const checkedCheckboxes = document.querySelectorAll('.word-checkbox:checked');

        selectAllCheckbox.checked = checkedCheckboxes.length === wordCheckboxes.length && wordCheckboxes.length > 0;
        selectAllCheckbox.indeterminate = checkedCheckboxes.length > 0 && checkedCheckboxes.length < wordCheckboxes.length;
    } catch (e) {
        console.error("Error updating selectAll state:", e);
    }
}

function getExportFormData() {
    try {
        return {
            deckName: document.getElementById('deckName')?.value || '',
            cardFormat: document.getElementById('cardFormat')?.value || 'basic',
            includePronunciation: document.getElementById('includePronunciation')?.checked || false,
            includeExamples: document.getElementById('includeExamples')?.checked || false,
            updateStatus: document.getElementById('updateStatus')?.checked || false
        };
    } catch (e) {
        console.error("Error getting export form data:", e);
        return {
            deckName: '',
            cardFormat: 'basic',
            includePronunciation: false,
            includeExamples: false,
            updateStatus: false
        };
    }
}

function updateWordStatuses(wordIds, status) {
    try {
        // Show loading indicator
        showAlert('Updating word statuses...', 'info');

        // Process words in smaller batches to reduce the chance of conflicts
        const batchSize = 10;
        const totalBatches = Math.ceil(wordIds.length / batchSize);
        let completedBatches = 0;
        let totalUpdated = 0;

        console.log(`Processing ${wordIds.length} words in ${totalBatches} batches of ${batchSize}`);

        // Process each batch sequentially
        function processBatch(batchIndex) {
            // Get the current batch of word IDs
            const startIdx = batchIndex * batchSize;
            const endIdx = Math.min(startIdx + batchSize, wordIds.length);
            const currentBatch = wordIds.slice(startIdx, endIdx);

            console.log(`Processing batch ${batchIndex + 1}/${totalBatches} with ${currentBatch.length} words`);

            // Send the batch update request
            fetch('/api/batch-update-status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    word_ids: currentBatch,
                    status: parseInt(status)
                })
            })
            .then(response => response.json())
            .then(data => {
                completedBatches++;

                // Count updated words even if there were errors
                if (data.updated_count) {
                    totalUpdated += data.updated_count;
                } else if (data.success) {
                    totalUpdated += currentBatch.length; // Assume all were updated if count not provided
                }

                // Show progress
                showAlert(`Processing... (${completedBatches}/${totalBatches} batches)`, 'info');

                // Process next batch or finish
                if (batchIndex + 1 < totalBatches) {
                    // Process next batch with a small delay to reduce server load
                    setTimeout(() => processBatch(batchIndex + 1), 300);
                } else {
                    // All batches completed
                    showAlert(`Successfully updated ${totalUpdated} word(s).`, 'success');

                    // Reload page to show updated statuses
                    setTimeout(() => {
                        window.location.reload();
                    }, 1500);
                }
            })
            .catch(error => {
                console.error('Error in batch:', error);

                // Even if this batch had an error, try to continue with the next one
                completedBatches++;

                if (batchIndex + 1 < totalBatches) {
                    setTimeout(() => processBatch(batchIndex + 1), 300);
                } else {
                    // All batches attempted
                    showAlert(`Completed with some errors. ${totalUpdated} word(s) updated.`, 'warning');
                    setTimeout(() => window.location.reload(), 1500);
                }
            });
        }

        // Start processing with the first batch
        processBatch(0);
    } catch (e) {
        console.error("Error updating word statuses:", e);
        showAlert('An unexpected error occurred.', 'danger');
    }
}

function showAlert(message, type = 'info') {
    try {
        // Create alert element
        const alertsContainer = document.getElementById('alertsContainer') || createAlertsContainer();

        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show`;
        alert.role = 'alert';

        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;

        // Add to container
        alertsContainer.appendChild(alert);

        // Auto dismiss after 5 seconds unless it's an error
        if (type !== 'danger') {
            setTimeout(() => {
                try {
                    const bsAlert = new bootstrap.Alert(alert);
                    bsAlert.close();
                } catch (e) {
                    // Fallback if bootstrap alert fails
                    alert.style.display = 'none';
                }
            }, 5000);
        }
    } catch (e) {
        console.error("Error showing alert:", e);
        // Fallback alert
        console.log(`${type.toUpperCase()}: ${message}`);
    }
}

function createAlertsContainer() {
    try {
        const container = document.createElement('div');
        container.id = 'alertsContainer';
        container.className = 'position-fixed top-0 end-0 p-3';
        container.style.zIndex = '1050';
        document.body.appendChild(container);
        return container;
    } catch (e) {
        console.error("Error creating alerts container:", e);
        return document.createElement('div'); // Return dummy element to prevent errors
    }
}

// Force fix to run after everything else
window.addEventListener('load', function() {
    setTimeout(function() {
        // Final check to ensure bulk actions work with Select All
        const selectAllCB = document.getElementById('selectAll');
        const bulkActionsDropdown = document.getElementById('bulkActionsDropdown');

        if (selectAllCB && bulkActionsDropdown) {
            console.log("Applying final force fix");

            // Apply direct event handler that will override any others
            selectAllCB.onclick = function() {
                // Get current state
                const isChecked = this.checked;
                console.log(`Force fix: Select All clicked, now ${isChecked ? 'checked' : 'unchecked'}`);

                // Apply to all checkboxes
                document.querySelectorAll('.word-checkbox').forEach(cb => {
                    cb.checked = isChecked;
                });

                // Force enable all bulk actions if at least one checkbox is checked
                if (isChecked) {
                    // Enable dropdown button
                    bulkActionsDropdown.classList.remove('disabled');
                    bulkActionsDropdown.removeAttribute('disabled');
                    bulkActionsDropdown.style.pointerEvents = 'auto';

                    // Enable all bulk action items
                    document.querySelectorAll('.bulk-action').forEach(item => {
                        item.classList.remove('disabled');
                        item.style.pointerEvents = 'auto';
                    });

                    // Enable export button
                    const exportBtn = document.getElementById('bulkExportBtn');
                    if (exportBtn) exportBtn.disabled = false;

                    console.log("Force fix applied: Bulk actions enabled");
                } else {
                    // Disable everything
                    bulkActionsDropdown.classList.add('disabled');

                    // Disable all bulk action items
                    document.querySelectorAll('.bulk-action').forEach(item => {
                        item.classList.add('disabled');
                    });

                    // Disable export button
                    const exportBtn = document.getElementById('bulkExportBtn');
                    if (exportBtn) exportBtn.disabled = true;

                    console.log("Force fix applied: Bulk actions disabled");
                }
            };
        }
    }, 500); // Wait 500ms after everything has loaded
});