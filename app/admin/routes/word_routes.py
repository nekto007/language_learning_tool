# app/admin/routes/word_routes.py

"""
Word Management Routes для административной панели
Маршруты для управления словами, переводами и статистикой слов
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user

from app.admin.services.word_management_service import WordManagementService
from app.admin.utils.decorators import admin_required, handle_admin_errors
from app.admin.utils.cache import clear_admin_cache
from app.admin.utils.export_helpers import export_words_csv, export_words_json, export_words_txt
from app.admin.utils.import_helpers import delete_import_data, load_import_data, save_import_data
from app.auth.models import User
from app.words.models import CollectionWords
from app.utils.db import db

# Создаем blueprint для word routes
word_bp = Blueprint('word_admin', __name__)

logger = logging.getLogger(__name__)


@word_bp.route('/words')
@admin_required
def word_management():
    """Главная страница управления словами"""
    try:
        stats = WordManagementService.get_word_statistics()

        if 'error' in stats:
            flash(f'Ошибка при загрузке данных: {stats["error"]}', 'danger')
            return redirect(url_for('admin.dashboard'))

        return render_template(
            'admin/words/index.html',
            words_total=stats['words_total'],
            status_stats=stats['status_stats'],
            recent_words=stats['recent_words'],
            words_without_translation=stats['words_without_translation']
        )
    except Exception as e:
        logger.error(f"Error in word management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@word_bp.route('/words/bulk-status-update', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def bulk_status_update():
    """Массовое обновление статусов слов"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            words = data.get('words', [])  # Список английских слов
            status = data.get('status')  # Новый статус
            user_id = data.get('user_id')  # ID пользователя (опционально)

            success, updated_count, total_requested, error = \
                WordManagementService.bulk_update_word_status(words, status, user_id)

            if not success:
                return jsonify({
                    'success': False,
                    'error': error
                }), 400 if error == 'Требуются words и status' else 500

            # Очищаем кэш после массового обновления
            clear_admin_cache()

            return jsonify({
                'success': True,
                'updated_count': updated_count,
                'total_requested': total_requested
            })

        except Exception as e:
            logger.error(f"Error in bulk status update: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # GET запрос - показать форму
    users = User.query.filter_by(active=True).all()
    return render_template('admin/words/bulk_status_update.html', users=users)


@word_bp.route('/words/export')
@admin_required
def export_words():
    """Экспорт слов по различным критериям"""
    status = request.args.get('status')
    format_type = request.args.get('format', 'json')  # json, csv, txt
    user_id = request.args.get('user_id', type=int)

    try:
        words = WordManagementService.get_words_for_export(status, user_id)

        if format_type == 'json':
            return export_words_json(words, status)
        elif format_type == 'csv':
            return export_words_csv(words, status)
        elif format_type == 'txt':
            return export_words_txt(words, status)
        else:
            flash('Неподдерживаемый формат экспорта', 'danger')
            return redirect(url_for('word_admin.word_management'))

    except Exception as e:
        logger.error(f"Error exporting words: {str(e)}")
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('word_admin.word_management'))


@word_bp.route('/words/import-translations', methods=['GET', 'POST'])
@admin_required
def import_translations():
    """Импорт переводов из файла"""
    if request.method == 'POST':
        action = request.form.get('action', 'preview')

        try:
            if action == 'preview':
                # Первый этап - предварительный просмотр
                if 'translation_file' not in request.files:
                    flash('Файл не выбран', 'danger')
                    return redirect(request.url)

                file = request.files['translation_file']
                if file.filename == '':
                    flash('Файл не выбран', 'danger')
                    return redirect(request.url)

                # SECURITY: Validate uploaded file
                from app.utils.file_security import validate_text_file_upload
                is_valid, error_msg = validate_text_file_upload(
                    file,
                    allowed_extensions={'txt', 'csv'},
                    max_size_mb=5
                )

                if not is_valid:
                    flash(f'Ошибка валидации файла: {error_msg}', 'danger')
                    return redirect(request.url)

                # Читаем содержимое файла
                content = file.read().decode('utf-8')

                # Парсим файл через сервис
                existing_words, missing_words, errors = \
                    WordManagementService.parse_import_file(content)

                # Сохраняем данные во временный файл вместо сессии
                import_id = save_import_data({
                    'existing_words': existing_words,
                    'missing_words': missing_words,
                    'errors': errors
                })

                # Сохраняем только ID в сессии
                session['import_id'] = import_id

                return render_template('admin/words/import_preview.html',
                                       existing_words=existing_words,
                                       missing_words=missing_words,
                                       errors=errors,
                                       import_id=import_id)

            elif action == 'confirm':
                # Второй этап - подтверждение импорта
                import_id = request.form.get('import_id') or session.get('import_id')

                if not import_id:
                    flash('Данные для импорта не найдены. Загрузите файл заново.', 'danger')
                    return redirect(request.url)

                import_data = load_import_data(import_id)
                if not import_data:
                    flash('Данные для импорта устарели. Загрузите файл заново.', 'danger')
                    return redirect(request.url)

                existing_words = import_data['existing_words']
                missing_words = import_data['missing_words']

                # Получаем выбранные для добавления отсутствующие слова
                words_to_add = request.form.getlist('add_missing_words')

                # Импортируем через сервис
                updated_count, added_count = WordManagementService.import_translations(
                    existing_words, missing_words, words_to_add
                )

                # Удаляем временный файл
                delete_import_data(import_id)
                session.pop('import_id', None)

                messages = []
                if updated_count > 0:
                    messages.append(f'Обновлено слов: {updated_count}')
                if added_count > 0:
                    messages.append(f'Добавлено новых слов: {added_count}')

                if messages:
                    flash('; '.join(messages), 'success')
                else:
                    flash('Никаких изменений не было внесено', 'info')

                logger.info(
                    f"Translations import completed by {current_user.username}: "
                    f"{updated_count} updated, {added_count} added"
                )

        except Exception as e:
            logger.error(f"Error importing translations: {str(e)}")
            flash(f'Ошибка при импорте: {str(e)}', 'danger')

    return render_template('admin/words/import_translations.html')


@word_bp.route('/words/statistics')
@admin_required
def word_statistics():
    """Детальная статистика по словам"""
    try:
        stats = WordManagementService.get_detailed_statistics()

        if 'error' in stats:
            flash(f'Ошибка при получении статистики: {stats["error"]}', 'danger')
            return redirect(url_for('word_admin.word_management'))

        return render_template(
            'admin/words/statistics.html',
            status_stats=stats['status_stats'],
            level_stats=stats['level_stats'],
            top_users=stats['top_users'],
            book_stats=stats['book_stats']
        )
    except Exception as e:
        logger.error(f"Error getting word statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('word_admin.word_management'))
