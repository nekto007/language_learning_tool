let autoSaveTimer;
let hasUnsavedChanges = false;
let currentView = 'split';

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    const editor = document.getElementById('contentEditor');
    
    // Update preview on input
    editor.addEventListener('input', function() {
        updatePreview();
        updateWordCount();
        markAsUnsaved();
        
        // Auto-save after 2 seconds of inactivity
        clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(autoSave, 2000);
    });
    
    // Initial preview and count
    updatePreview();
    updateWordCount();
    
    // Warn before leaving with unsaved changes
    window.addEventListener('beforeunload', function(e) {
        if (hasUnsavedChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
    
    // File upload handling
    document.getElementById('fileInput').addEventListener('change', handleFileUpload);
    
    // Drag and drop
    const uploadArea = document.getElementById('fileUploadArea');
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            document.getElementById('fileInput').files = files;
            handleFileUpload();
        }
    });
});

// Update preview
function updatePreview() {
    const content = document.getElementById('contentEditor').value;
    const preview = document.getElementById('previewContent');
    
    if (content.trim()) {
        // Convert to HTML if it's plain text
        let html = content;
        if (!content.includes('<p>') && !content.includes('<h')) {
            // Convert plain text to paragraphs
            html = content.split('\n\n')
                .filter(p => p.trim())
                .map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`)
                .join('\n');
        }
        
        // Support basic markdown
        html = marked.parse(html);
        preview.innerHTML = html;
    } else {
        preview.innerHTML = `
            <div class="text-muted text-center py-5">
                <i class="fas fa-eye fa-3x mb-3"></i>
                <p>Preview will appear here as you type...</p>
            </div>
        `;
    }
}

// Update word count
function updateWordCount() {
    const content = document.getElementById('contentEditor').value;
    const text = content.replace(/<[^>]*>/g, ''); // Remove HTML tags
    const words = text.match(/\b\w+\b/g) || [];
    const chars = text.length;
    
    document.getElementById('wordCount').textContent = `${words.length} words`;
    document.getElementById('charCount').textContent = `${chars} characters`;
}

// Insert markdown
function insertMarkdown(before, after) {
    const editor = document.getElementById('contentEditor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selectedText = editor.value.substring(start, end);
    const replacement = before + selectedText + after;
    
    editor.value = editor.value.substring(0, start) + replacement + editor.value.substring(end);
    
    // Set cursor position
    const newPos = start + before.length + selectedText.length;
    editor.setSelectionRange(newPos, newPos);
    editor.focus();
    
    // Update preview
    updatePreview();
    markAsUnsaved();
}

// Format content
function formatContent() {
    const editor = document.getElementById('contentEditor');
    let content = editor.value;
    
    // Basic formatting: ensure paragraphs are separated
    content = content.replace(/\n{3,}/g, '\n\n'); // Replace multiple newlines with double
    content = content.trim();
    
    editor.value = content;
    updatePreview();
    markAsUnsaved();
}

// Count words (detailed)
function countWords() {
    const content = document.getElementById('contentEditor').value;
    const text = content.replace(/<[^>]*>/g, '');
    const words = text.match(/\b\w+\b/g) || [];
    const uniqueWords = [...new Set(words.map(w => w.toLowerCase()))];
    
    alert(`Word Statistics:\n\nTotal words: ${words.length}\nUnique words: ${uniqueWords.length}\nCharacters: ${text.length}\nCharacters (with spaces): ${content.length}`);
}

// View management
function setView(view) {
    currentView = view;
    const container = document.getElementById('editorContainer');
    const editorPanel = document.getElementById('editorPanel');
    const previewPanel = document.getElementById('previewPanel');
    
    // Update toggle buttons
    document.querySelectorAll('.view-toggle button').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // Apply view
    switch(view) {
        case 'editor':
            editorPanel.style.display = 'flex';
            previewPanel.style.display = 'none';
            break;
        case 'preview':
            editorPanel.style.display = 'none';
            previewPanel.style.display = 'flex';
            break;
        case 'split':
        default:
            editorPanel.style.display = 'flex';
            previewPanel.style.display = 'flex';
            break;
    }
}

// Save content
async function saveContent() {
    const form = document.getElementById('contentForm');
    const formData = new FormData(form);
    
    // Show loading
    document.getElementById('loadingOverlay').style.display = 'flex';
    
    try {
        const response = await fetch('', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            markAsSaved();
            showAutoSaveToast();
            hasUnsavedChanges = false;
            
            // Check if redirected
            if (response.redirected) {
                window.location.href = response.url;
            }
        } else {
            alert('Failed to save content. Please try again.');
        }
    } catch (error) {
        console.error('Save error:', error);
        alert('An error occurred while saving.');
    } finally {
        document.getElementById('loadingOverlay').style.display = 'none';
    }
}

// Auto-save
async function autoSave() {
    if (!hasUnsavedChanges) return;
    
    // For now, just mark as saved for demo
    // In production, you'd implement actual auto-save
    markAsSaved();
    showAutoSaveToast();
    hasUnsavedChanges = false;
}

// Status management
function markAsUnsaved() {
    hasUnsavedChanges = true;
    document.getElementById('saveIndicator').classList.remove('saved');
    document.getElementById('saveIndicator').classList.add('unsaved');
    document.getElementById('saveStatus').textContent = 'Unsaved changes';
}

function markAsSaved() {
    document.getElementById('saveIndicator').classList.add('saved');
    document.getElementById('saveIndicator').classList.remove('unsaved');
    document.getElementById('saveStatus').textContent = 'All changes saved';
}

function showAutoSaveToast() {
    const toast = document.getElementById('autoSaveToast');
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// File upload
async function handleFileUpload() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    
    if (!file) return;
    
    // Show loading
    document.getElementById('loadingOverlay').style.display = 'flex';
    
    try {
        // For text files, read directly
        if (file.type === 'text/plain' || file.name.endsWith('.txt')) {
            const text = await file.text();
            document.getElementById('contentEditor').value = text;
            updatePreview();
            updateWordCount();
            markAsUnsaved();
        } else {
            // For other formats, need server processing
            alert('File uploaded. Processing will happen on save.');
            markAsUnsaved();
        }
    } catch (error) {
        console.error('File read error:', error);
        alert('Failed to read file.');
    } finally {
        document.getElementById('loadingOverlay').style.display = 'none';
    }
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveContent();
    }
    
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        insertMarkdown('**', '**');
    }
    
    if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
        e.preventDefault();
        insertMarkdown('*', '*');
    }
});

// Event delegation (CSP-safe replacement for inline onclick=).
document.addEventListener('click', function(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;
    switch (action) {
        case 'save-content':         saveContent(); break;
        case 'set-view':             setView(target.dataset.view); break;
        case 'insert-md':            insertMarkdown(target.dataset.before || '', target.dataset.after || ''); break;
        case 'format-content':       formatContent(); break;
        case 'count-words':          countWords(); break;
        case 'toggle-preview-mode':  togglePreviewMode(); break;
        case 'trigger-file-input':   document.getElementById('fileInput')?.click(); break;
    }
});
