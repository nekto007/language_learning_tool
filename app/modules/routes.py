from flask import render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.modules import modules_bp
from app.modules.service import ModuleService
from app.modules.decorators import module_required


@modules_bp.route('/api/modules/user')
@login_required
def get_user_modules():
    """API endpoint для получения модулей пользователя"""
    modules = ModuleService.get_user_modules(current_user.id, enabled_only=True)
    return jsonify({
        'success': True,
        'modules': [module.to_dict() for module in modules]
    })


@modules_bp.route('/api/modules/all')
@login_required
def get_all_modules():
    """API endpoint для получения всех активных модулей"""
    modules = ModuleService.get_active_modules()
    return jsonify({
        'success': True,
        'modules': [module.to_dict() for module in modules]
    })


@modules_bp.route('/api/modules/enabled-codes')
@login_required
def get_enabled_module_codes():
    """API endpoint для получения кодов включенных модулей пользователя"""
    codes = ModuleService.get_user_enabled_module_codes(current_user.id)
    return jsonify({
        'success': True,
        'codes': codes
    })


@modules_bp.route('/modules/settings')
@login_required
def settings():
    """Страница настроек модулей пользователя"""
    user_modules = ModuleService.get_user_modules(current_user.id, enabled_only=False)
    all_modules = ModuleService.get_active_modules()

    # Создаем словарь для удобного доступа
    from app.modules.models import UserModule
    user_module_map = {}
    for um in UserModule.query.filter_by(user_id=current_user.id).all():
        user_module_map[um.module_id] = um

    return render_template('modules/settings.html',
                          all_modules=all_modules,
                          user_module_map=user_module_map)


@modules_bp.route('/api/modules/<int:module_id>/toggle', methods=['POST'])
@login_required
def toggle_module(module_id):
    """Toggle module on/off for current user"""
    try:
        new_state = ModuleService.toggle_module_for_user(current_user.id, module_id)
        return jsonify({
            'success': True,
            'enabled': new_state
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
