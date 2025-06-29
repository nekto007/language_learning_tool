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

  function updateStatusDisplay(data) {
    let statusIcon, statusTitle, statusClass, statusContent;

    switch (data.status) {
      case 'queued':
        statusIcon = 'fas fa-clock';
        statusTitle = 'Обработка слов поставлена в очередь';
        statusClass = 'info';
        statusContent = `
          <p>Обработка слов поставлена в очередь и скоро начнется.</p>
          <small class="text-muted">Поставлено в очередь: ${formatDateTime(data.queued_at)}</small>
        `;
        break;

      case 'processing':
        statusIcon = 'fas fa-cogs fa-spin';
        statusTitle = 'Обработка слов в процессе';
        statusClass = 'primary';

        // Показываем прогресс-бар с процентами, если они доступны
        let progressBar = '';
        if (data.progress !== undefined) {
          progressBar = `
            <div class="progress mt-2">
              <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" 
                   style="width: ${data.progress}%" aria-valuenow="${data.progress}" aria-valuemin="0" aria-valuemax="100">
                ${data.progress}%
              </div>
            </div>`;
        } else {
          progressBar = `
            <div class="progress mt-2">
              <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" 
                   style="width: 100%"></div>
            </div>`;
        }

        // Добавляем информацию о промежуточных результатах, если доступна
        let wordsInfo = '';
        if (data.words_processed_so_far) {
          wordsInfo = `<p class="small mt-2">Обработано слов: ${data.words_processed_so_far}</p>`;
        }

        statusContent = `
          <p>${data.message || 'Обработка слов из книги...'}</p>
          ${data.book_size ? `<p class="small">Размер книги: ${formatFileSize(data.book_size)}</p>` : ''}
          ${progressBar}
          ${wordsInfo}
          <small class="text-muted mt-2 d-block">Начато: ${formatDateTime(data.started_at)}</small>
        `;
        break;

      case 'error':
        statusIcon = 'fas fa-exclamation-triangle';
        statusTitle = 'Ошибка обработки слов';
        statusClass = 'danger';
        statusContent = `
          <p>Ошибка при обработке слов:</p>
          <div class="alert alert-danger">
            ${data.message || 'Unknown error'}
          </div>
          <button class="btn btn-sm btn-outline-primary" onclick="location.href='${window.location.pathname}'">
            <i class="fas fa-sync-alt"></i> Перезагрузить страницу
          </button>
          ${data.completed_at ? `<small class="text-muted mt-2 d-block">Завершено: ${formatDateTime(data.completed_at)}</small>` : ''}
        `;
        break;

      case 'timeout':
        statusIcon = 'fas fa-exclamation-circle';
        statusTitle = 'Тайм-аут обработки слов';
        statusClass = 'warning';
        statusContent = `
          <p>Обработка прервана по тайм-ауту. Книга может быть слишком большой или содержать сложное содержимое.</p>
          <p class="small">You can still use the book, but word statistics might be incomplete.</p>
          <button class="btn btn-sm btn-outline-primary" onclick="location.href='${window.location.pathname}'">
            <i class="fas fa-sync-alt"></i> Перезагрузить страницу
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