# app/admin/routes/audio_routes.py

"""
Audio Management Routes для административной панели
Маршруты для управления аудио файлами и их статистикой
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin.services.audio_management_service import AudioManagementService
from app.admin.utils.decorators import admin_required, handle_admin_errors
from app.admin.utils.cache import clear_admin_cache
from app.admin.utils.export_helpers import export_audio_list_csv, export_audio_list_json, export_audio_list_txt

# Создаем blueprint для audio routes
audio_bp = Blueprint('audio_admin', __name__)

logger = logging.getLogger(__name__)


@audio_bp.route('/audio')
@admin_required
def audio_management():
    """Главная страница управления аудио"""
    try:
        from config.settings import MEDIA_FOLDER

        stats = AudioManagementService.get_audio_statistics(MEDIA_FOLDER)

        if 'error' in stats:
            flash(f'Ошибка при загрузке данных: {stats["error"]}', 'danger')
            return redirect(url_for('admin.dashboard'))

        return render_template(
            'admin/audio/index.html',
            words_total=stats['words_total'],
            words_with_audio=stats['words_with_audio'],
            words_without_audio=stats['words_without_audio'],
            problematic_audio=stats['problematic_audio'],
            recent_audio_updates=stats['recent_audio_updates'],
            media_folder=stats['media_folder']
        )
    except Exception as e:
        logger.error(f"Error in audio management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@audio_bp.route('/audio/update-download-status', methods=['POST'])
@admin_required
def update_audio_download_status():
    """Обновление статуса загрузки аудио файлов"""
    try:
        from config.settings import MEDIA_FOLDER, COLLECTIONS_TABLE

        # Получаем параметры
        data = request.get_json()
        table_name = data.get('table', COLLECTIONS_TABLE)

        # Определяем имя колонки в зависимости от таблицы
        column_name = "english_word" if table_name == COLLECTIONS_TABLE else "phrasal_verb"

        # Обновляем статус загрузки через сервис
        updated_count = AudioManagementService.update_download_status(
            table_name, column_name, MEDIA_FOLDER
        )

        logger.info(f"Audio download status updated by {current_user.username}: {updated_count} records")

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'table_name': table_name
        })

    except Exception as e:
        logger.error(f"Error updating audio download status: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@audio_bp.route('/audio/fix-listening-fields', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def fix_audio_listening_fields():
    """Исправление полей прослушивания"""
    try:
        success, fixed_count, message = AudioManagementService.fix_listening_fields()

        if success:
            # Очищаем кэш после изменения данных
            clear_admin_cache()

            logger.info(f"Audio listening fields fixed by {current_user.username}: {fixed_count} records")

            return jsonify({
                'success': True,
                'message': message,
                'fixed_count': fixed_count
            })
        else:
            return jsonify({
                'success': False,
                'error': message
            }), 500

    except Exception as e:
        logger.error(f"Error fixing listening fields: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@audio_bp.route('/audio/normalize-listening-fields', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def normalize_audio_listening_fields():
    """
    Нормализация полей listening: убирает обертку [sound:...] и оставляет чистое имя файла.
    Это позволяет использовать аудио напрямую в приложении.
    """
    try:
        success, fixed_count, message = AudioManagementService.normalize_listening_fields()

        if success:
            clear_admin_cache()
            logger.info(f"Audio listening fields normalized by {current_user.username}: {fixed_count} records")

            return jsonify({
                'success': True,
                'message': message,
                'fixed_count': fixed_count
            })
        else:
            return jsonify({
                'success': False,
                'error': message
            }), 500

    except Exception as e:
        logger.error(f"Error normalizing listening fields: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@audio_bp.route('/audio/fix-all', methods=['POST'])
@admin_required
def fix_all_audio():
    """Комбинированная операция: обновить статус + исправить HTTP + нормализовать формат"""
    results: list[dict] = []

    # 1. Обновить статус загрузки
    try:
        from config.settings import MEDIA_FOLDER, COLLECTIONS_TABLE
        column_name = "english_word"
        updated_count = AudioManagementService.update_download_status(
            COLLECTIONS_TABLE, column_name, MEDIA_FOLDER
        )
        results.append({'step': 'Обновление статуса загрузки', 'success': True, 'count': updated_count})
        logger.info(f"Audio download status updated by {current_user.username}: {updated_count} records")
    except Exception as e:
        logger.error(f"Error updating download status in fix-all: {e}")
        results.append({'step': 'Обновление статуса загрузки', 'success': False, 'error': str(e)})

    # 2. Исправить HTTP URL → чистое имя файла
    try:
        success, fixed_count, message = AudioManagementService.fix_listening_fields()
        results.append({'step': 'Исправление HTTP URL', 'success': success, 'count': fixed_count if success else 0})
        if success:
            logger.info(f"Audio listening fields fixed by {current_user.username}: {fixed_count} records")
    except Exception as e:
        logger.error(f"Error fixing listening fields in fix-all: {e}")
        results.append({'step': 'Исправление HTTP URL', 'success': False, 'error': str(e)})

    # 3. Нормализовать [sound:...] → чистое имя файла
    try:
        success, fixed_count, message = AudioManagementService.normalize_listening_fields()
        results.append({'step': 'Нормализация формата', 'success': success, 'count': fixed_count if success else 0})
        if success:
            logger.info(f"Audio listening fields normalized by {current_user.username}: {fixed_count} records")
    except Exception as e:
        logger.error(f"Error normalizing listening fields in fix-all: {e}")
        results.append({'step': 'Нормализация формата', 'success': False, 'error': str(e)})

    clear_admin_cache()

    all_success = all(r['success'] for r in results)
    return jsonify({
        'success': all_success,
        'results': results
    }), 200 if all_success else 207


@audio_bp.route('/audio/get-download-list')
@admin_required
def get_audio_download_list():
    """Получение списка слов для загрузки аудио"""
    try:
        # Получаем параметры фильтрации
        pattern = request.args.get('pattern')
        format_type = request.args.get('format', 'txt')

        # Получаем список слов через сервис
        words = AudioManagementService.get_download_list(pattern)

        if not words:
            flash('Нет слов для загрузки аудио', 'info')
            return redirect(url_for('audio_admin.audio_management'))

        # Экспортируем в нужном формате
        if format_type == 'json':
            return export_audio_list_json(words, pattern)
        elif format_type == 'csv':
            return export_audio_list_csv(words, pattern)
        else:
            return export_audio_list_txt(words, pattern)

    except Exception as e:
        logger.error(f"Error getting download list: {str(e)}")
        flash(f'Ошибка при получении списка: {str(e)}', 'danger')
        return redirect(url_for('audio_admin.audio_management'))


@audio_bp.route('/audio/statistics')
@admin_required
def audio_statistics():
    """Детальная статистика по аудио"""
    try:
        stats = AudioManagementService.get_detailed_statistics()

        if 'error' in stats:
            flash(f'Ошибка при получении статистики: {stats["error"]}', 'danger')
            return redirect(url_for('audio_admin.audio_management'))

        return render_template(
            'admin/audio/statistics.html',
            download_stats=stats['download_stats'],
            listening_stats=stats['listening_stats'],
            level_audio_stats=stats['level_audio_stats']
        )
    except Exception as e:
        logger.error(f"Error getting audio statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('audio_admin.audio_management'))
