"""
Admin routes for module management
"""
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps

from app.modules.service import ModuleService
from app.modules.models import SystemModule
from app.auth.models import User
from app.utils.db import db


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('У вас нет доступа к этой странице.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def register_module_admin_routes(admin_bp):
    """Register module management routes to admin blueprint"""

    # Check if routes have already been registered to avoid re-registration errors
    if hasattr(admin_bp, '_module_admin_routes_registered'):
        return

    @admin_bp.route('/modules')
    @login_required
    @admin_required
    def modules_list():
        """List all modules with statistics"""
        modules = ModuleService.get_all_modules()
        stats = ModuleService.get_module_statistics()
        return render_template('admin/modules/list.html', modules=modules, stats=stats)

    @admin_bp.route('/modules/create', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def modules_create():
        """Create a new module"""
        if request.method == 'POST':
            try:
                module = ModuleService.create_module(
                    code=request.form.get('code'),
                    name=request.form.get('name'),
                    description=request.form.get('description', ''),
                    icon=request.form.get('icon', ''),
                    is_active=request.form.get('is_active') == 'on',
                    is_default=request.form.get('is_default') == 'on',
                    order=int(request.form.get('order', 0)),
                    blueprint_name=request.form.get('blueprint_name', ''),
                    url_prefix=request.form.get('url_prefix', '')
                )
                flash(f'Модуль "{module.name}" создан успешно!', 'success')
                return redirect(url_for('admin.modules_list'))
            except Exception as e:
                flash(f'Ошибка при создании модуля: {str(e)}', 'error')

        return render_template('admin/modules/create.html')

    @admin_bp.route('/modules/<int:module_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def modules_edit(module_id):
        """Edit an existing module"""
        module = ModuleService.get_module_by_id(module_id)
        if not module:
            flash('Модуль не найден', 'error')
            return redirect(url_for('admin.modules_list'))

        if request.method == 'POST':
            try:
                ModuleService.update_module(
                    module_id=module_id,
                    name=request.form.get('name'),
                    description=request.form.get('description', ''),
                    icon=request.form.get('icon', ''),
                    is_active=request.form.get('is_active') == 'on',
                    is_default=request.form.get('is_default') == 'on',
                    order=int(request.form.get('order', 0)),
                    blueprint_name=request.form.get('blueprint_name', ''),
                    url_prefix=request.form.get('url_prefix', '')
                )
                flash(f'Модуль "{module.name}" обновлен успешно!', 'success')
                return redirect(url_for('admin.modules_list'))
            except Exception as e:
                flash(f'Ошибка при обновлении модуля: {str(e)}', 'error')

        # Get all users
        all_users = User.query.order_by(User.username).all()

        # Get user modules for this module
        from app.modules.models import UserModule
        user_modules = UserModule.query.filter_by(module_id=module_id).all()

        # Create user_modules_map for quick lookup
        user_modules_map = {um.user_id: um for um in user_modules}

        # Separate users with and without module
        users_with_module = [u for u in all_users if u.id in user_modules_map and user_modules_map[u.id].is_enabled]
        users_without_module = [u for u in all_users if u.id not in user_modules_map or not user_modules_map[u.id].is_enabled]

        # Get statistics for this module
        stats = ModuleService.get_module_statistics()
        module_stats = stats.get(module.code) if stats else None

        return render_template('admin/modules/edit.html',
                               module=module,
                               module_stats=module_stats,
                               all_users=all_users,
                               users_with_module=users_with_module,
                               users_without_module=users_without_module,
                               user_modules_map=user_modules_map)

    @admin_bp.route('/modules/<int:module_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def modules_delete(module_id):
        """Delete a module"""
        module = ModuleService.get_module_by_id(module_id)
        if not module:
            return jsonify({'success': False, 'error': 'Модуль не найден'}), 404

        try:
            ModuleService.delete_module(module_id)
            flash(f'Модуль "{module.name}" удален успешно!', 'success')
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @admin_bp.route('/modules/<int:module_id>/users')
    @login_required
    @admin_required
    def modules_users(module_id):
        """View users with access to a module"""
        module = ModuleService.get_module_by_id(module_id)
        if not module:
            flash('Модуль не найден', 'error')
            return redirect(url_for('admin.modules_list'))

        # Get all users with this module
        from app.modules.models import UserModule
        user_modules = UserModule.query.filter_by(module_id=module_id).all()

        return render_template('admin/modules/users.html', module=module, user_modules=user_modules)

    @admin_bp.route('/modules/users/<int:user_id>')
    @login_required
    @admin_required
    def user_modules(user_id):
        """View and manage modules for a specific user"""
        user = User.query.get(user_id)
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('admin.index'))

        user_modules = ModuleService.get_user_modules(user_id, enabled_only=False)
        all_modules = ModuleService.get_all_modules()

        # Determine which modules user doesn't have
        user_module_ids = {m.id for m in user_modules}
        available_modules = [m for m in all_modules if m.id not in user_module_ids]

        return render_template('admin/modules/user_modules.html',
                               user=user,
                               user_modules=user_modules,
                               available_modules=available_modules)

    @admin_bp.route('/modules/users/<int:user_id>/grant/<int:module_id>', methods=['POST'])
    @login_required
    @admin_required
    def grant_module(user_id, module_id):
        """Grant a module to a user"""
        try:
            ModuleService.grant_module_to_user(user_id, module_id, granted_by_admin=True)
            return jsonify({'success': True, 'message': 'Модуль выдан успешно'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @admin_bp.route('/modules/users/<int:user_id>/revoke/<int:module_id>', methods=['POST'])
    @login_required
    @admin_required
    def revoke_module(user_id, module_id):
        """Revoke a module from a user"""
        try:
            ModuleService.revoke_module_from_user(user_id, module_id)
            return jsonify({'success': True, 'message': 'Модуль отозван успешно'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @admin_bp.route('/modules/grant-bulk', methods=['POST'])
    @login_required
    @admin_required
    def grant_module_bulk():
        """Grant a module to multiple users"""
        try:
            module_id = int(request.form.get('module_id'))
            user_ids = request.form.getlist('user_ids[]')
            user_ids = [int(uid) for uid in user_ids]

            ModuleService.grant_modules_to_users(module_id, user_ids)

            return jsonify({'success': True, 'message': f'Модуль выдан {len(user_ids)} пользователям'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @admin_bp.route('/modules/statistics')
    @login_required
    @admin_required
    def modules_statistics():
        """View module usage statistics"""
        stats = ModuleService.get_module_statistics()
        return render_template('admin/modules/statistics.html', stats=stats)

    @admin_bp.route('/modules/<int:module_id>/users-data')
    @login_required
    @admin_required
    def get_module_users_data(module_id):
        """Get users data for a module (AJAX endpoint)"""
        module = ModuleService.get_module_by_id(module_id)
        if not module:
            return jsonify({'success': False, 'error': 'Модуль не найден'}), 404

        # Get all users
        all_users = User.query.order_by(User.username).all()

        # Get user modules for this module
        from app.modules.models import UserModule
        user_modules = UserModule.query.filter_by(module_id=module_id).all()
        user_modules_map = {um.user_id: um for um in user_modules}

        # Build response
        users_data = []
        for user in all_users:
            user_module = user_modules_map.get(user.id)
            users_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin,
                'has_module': user_module is not None and user_module.is_enabled,
                'granted_by_admin': user_module.granted_by_admin if user_module else False
            })

        return jsonify({
            'success': True,
            'module': {
                'id': module.id,
                'code': module.code,
                'name': module.name
            },
            'users': users_data
        })

    # Mark routes as registered
    admin_bp._module_admin_routes_registered = True
