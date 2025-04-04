// app/static/js/book_processing.js

document.addEventListener('DOMContentLoaded', function() {
  // Проверяем, есть ли на странице элемент статуса обработки
  const processingStatusElement = document.getElementById('processing-status');
  if (!processingStatusElement) return;

  const bookId = processingStatusElement.dataset.bookId;
  if (!bookId) return;

  let checkInterval;
  let retryCount = 0;
  const maxRetries = 120; // Максимальное количество попыток (10 минут при интервале 5 секунд)
  let statusVisible = false; // Флаг видимости элемента

  function checkProcessingStatus() {
    fetch(`/api/processing-status/${bookId}`)
      .then(response => response.json())
      .then(data => {
        if (!data || data.status === 'unknown') {
          // Скрываем элемент, если нет активной обработки
          if (statusVisible) {
            processingStatusElement.style.display = 'none';
            statusVisible = false;
          }
          clearInterval(checkInterval);
          return;
        }

        // Если есть статус обработки, показываем элемент
        if (!statusVisible) {
          processingStatusElement.style.display = 'block';
          statusVisible = true;
        }

        updateStatusDisplay(data);

        // Если обработка завершена или произошла ошибка, останавливаем опрос через некоторое время
        if (['success', 'error', 'timeout'].includes(data.status)) {
          // Для успешной обработки перезагружаем страницу
          if (data.status === 'success') {
            setTimeout(() => {
              window.location.reload();
            }, 3000); // Даем пользователю время увидеть сообщение об успехе
          } else {
            // Для ошибок просто останавливаем опрос через 1 минуту
            setTimeout(() => {
              clearInterval(checkInterval);
            }, 60000);
          }
        }

        // Увеличиваем счетчик попыток
        retryCount++;
        if (retryCount >= maxRetries) {
          clearInterval(checkInterval);
          updateStatusDisplay({
            status: 'error',
            message: 'Status check timed out. The processing may still be running in the background.'
          });
        }
      })
      .catch(error => {
        console.error('Error checking processing status:', error);
        processingStatusElement.innerHTML = `
          <div class="card-header">
            <h5 class="mb-0">Word Processing Status</h5>
          </div>
          <div class="card-body">
            <div class="alert alert-danger">
              <i class="fas fa-exclamation-triangle"></i> Error checking status: ${error.message}
            </div>
          </div>
        `;
        // Останавливаем опрос после нескольких ошибок
        if (retryCount > 5) {
          clearInterval(checkInterval);
        }
      });
  }

  function updateStatusDisplay(data) {
    let statusIcon, statusTitle, statusClass, statusContent;

    switch (data.status) {
      case 'queued':
        statusIcon = 'fas fa-clock';
        statusTitle = 'Word Processing Queued';
        statusClass = 'info';
        statusContent = `
          <p>Word processing has been queued and will start soon.</p>
          <small class="text-muted">Queued at: ${formatDateTime(data.queued_at)}</small>
        `;
        break;

      case 'processing':
        statusIcon = 'fas fa-cogs fa-spin';
        statusTitle = 'Word Processing In Progress';
        statusClass = 'primary';
        statusContent = `
          <p>Processing words from the book...</p>
          ${data.book_size ? `<p class="small">Book size: ${formatFileSize(data.book_size)}</p>` : ''}
          <div class="progress mt-2">
            <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" 
                 style="width: 100%"></div>
          </div>
          <small class="text-muted mt-2 d-block">Started at: ${formatDateTime(data.started_at)}</small>
        `;
        break;

      case 'success':
        statusIcon = 'fas fa-check-circle';
        statusTitle = 'Word Processing Complete';
        statusClass = 'success';
        statusContent = `
          <p>Processing completed successfully!</p>
          <ul class="mt-2 mb-2">
            <li>Total words: ${data.total_words ? formatNumber(data.total_words) : 'N/A'}</li>
            <li>Unique words: ${data.unique_words ? formatNumber(data.unique_words) : 'N/A'}</li>
            <li>Words processed: ${data.words_added ? formatNumber(data.words_added) : 'N/A'}</li>
            <li>Processing time: ${data.elapsed_time ? formatTime(data.elapsed_time) : 'N/A'}</li>
          </ul>
          <div class="alert alert-info mt-2">
            <i class="fas fa-sync-alt fa-spin"></i> Reloading page to show updated data...
          </div>
        `;
        break;

      case 'error':
        statusIcon = 'fas fa-exclamation-triangle';
        statusTitle = 'Word Processing Error';
        statusClass = 'danger';
        statusContent = `
          <p>Error during word processing:</p>
          <div class="alert alert-danger">
            ${data.message || 'Unknown error'}
          </div>
          <button class="btn btn-sm btn-outline-primary" onclick="location.href='${window.location.pathname}'">
            <i class="fas fa-sync-alt"></i> Reload Page
          </button>
          ${data.completed_at ? `<small class="text-muted mt-2 d-block">Completed at: ${formatDateTime(data.completed_at)}</small>` : ''}
        `;
        break;

      case 'timeout':
        statusIcon = 'fas fa-exclamation-circle';
        statusTitle = 'Word Processing Timeout';
        statusClass = 'warning';
        statusContent = `
          <p>Processing timed out. The book may be too large or contain complex content.</p>
          <p class="small">You can still use the book, but word statistics might be incomplete.</p>
          <button class="btn btn-sm btn-outline-primary" onclick="location.href='${window.location.pathname}'">
            <i class="fas fa-sync-alt"></i> Reload Page
          </button>
        `;
        break;

      default:
        statusIcon = 'fas fa-question-circle';
        statusTitle = 'Unknown Status';
        statusClass = 'secondary';
        statusContent = `<p>Unknown processing status: ${data.status}</p>`;
    }

    processingStatusElement.innerHTML = `
      <div class="card-header bg-${statusClass} text-white">
        <h5 class="mb-0"><i class="${statusIcon} me-2"></i> ${statusTitle}</h5>
      </div>
      <div class="card-body">
        ${statusContent}
      </div>
    `;
  }

  // Форматирование даты и времени
  function formatDateTime(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
  }

  // Форматирование времени (секунды в минуты:секунды)
  function formatTime(seconds) {
    if (!seconds) return 'N/A';
    seconds = Math.round(seconds);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (minutes > 0) {
      return `${minutes}m ${remainingSeconds}s`;
    } else {
      return `${seconds} seconds`;
    }
  }

  // Форматирование чисел (с разделителями тысяч)
  function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // Форматирование размера файла
  function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  // Сначала скрываем элемент, покажем его только если есть активная обработка
  processingStatusElement.style.display = 'none';

  // Запускаем первую проверку сразу
  checkProcessingStatus();

  // Устанавливаем интервал для проверки каждые 5 секунд
  checkInterval = setInterval(checkProcessingStatus, 5000);
});