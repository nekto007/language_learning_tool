# app/curriculum/backup.py

import gzip
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db

logger = logging.getLogger(__name__)


class CurriculumBackupManager:
    """Manager for curriculum data backup and restore operations"""

    def __init__(self, backup_dir: str = None):
        if backup_dir:
            self.backup_dir = backup_dir
        else:
            # Use a default directory that doesn't require current_app
            self.backup_dir = os.path.join(os.getcwd(), 'instance', 'backups', 'curriculum')
        self.ensure_backup_directory()

    def ensure_backup_directory(self):
        """Ensure backup directory exists"""
        os.makedirs(self.backup_dir, exist_ok=True)
        logger.info(f"Backup directory: {self.backup_dir}")

    def create_full_backup(self, include_progress: bool = True,
                           compress: bool = True) -> Dict[str, Any]:
        """
        Create a full backup of curriculum data
        
        Args:
            include_progress: Whether to include user progress data
            compress: Whether to compress the backup file
            
        Returns:
            Backup metadata
        """
        timestamp = datetime.now(timezone.utc)
        backup_id = timestamp.strftime("%Y%m%d_%H%M%S")

        try:
            # Collect all curriculum data
            backup_data = {
                'metadata': {
                    'backup_id': backup_id,
                    'created_at': timestamp.isoformat(),
                    'version': '1.0',
                    'include_progress': include_progress,
                    'compressed': compress
                },
                'cefr_levels': self._export_cefr_levels(),
                'modules': self._export_modules(),
                'lessons': self._export_lessons()
            }

            if include_progress:
                backup_data['lesson_progress'] = self._export_lesson_progress()

            # Save backup
            filename = f"curriculum_backup_{backup_id}"
            if compress:
                filename += ".json.gz"
                backup_path = os.path.join(self.backup_dir, filename)
                with gzip.open(backup_path, 'wt', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
            else:
                filename += ".json"
                backup_path = os.path.join(self.backup_dir, filename)
                with open(backup_path, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)

            # Calculate file size
            file_size = os.path.getsize(backup_path)

            backup_metadata = {
                'backup_id': backup_id,
                'filename': filename,
                'filepath': backup_path,
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'created_at': timestamp.isoformat(),
                'include_progress': include_progress,
                'compressed': compress,
                'records': {
                    'cefr_levels': len(backup_data['cefr_levels']),
                    'modules': len(backup_data['modules']),
                    'lessons': len(backup_data['lessons']),
                    'lesson_progress': len(backup_data.get('lesson_progress', []))
                }
            }

            # Save metadata
            self._save_backup_metadata(backup_metadata)

            logger.info(f"Created backup: {filename} ({backup_metadata['size_mb']} MB)")
            return backup_metadata

        except Exception as e:
            logger.error(f"Error creating backup: {str(e)}")
            raise

    def create_incremental_backup(self, since: datetime) -> Dict[str, Any]:
        """
        Create an incremental backup since specified date
        
        Args:
            since: DateTime to backup changes since
            
        Returns:
            Backup metadata
        """
        timestamp = datetime.now(timezone.utc)
        backup_id = f"incremental_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        try:
            # Get modified records since specified date
            backup_data = {
                'metadata': {
                    'backup_id': backup_id,
                    'backup_type': 'incremental',
                    'created_at': timestamp.isoformat(),
                    'since': since.isoformat(),
                    'version': '1.0'
                },
                'lessons': self._export_lessons_since(since),
                'lesson_progress': self._export_progress_since(since)
            }

            # Save incremental backup
            filename = f"{backup_id}.json.gz"
            backup_path = os.path.join(self.backup_dir, filename)

            with gzip.open(backup_path, 'wt', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)

            file_size = os.path.getsize(backup_path)

            backup_metadata = {
                'backup_id': backup_id,
                'backup_type': 'incremental',
                'filename': filename,
                'filepath': backup_path,
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'created_at': timestamp.isoformat(),
                'since': since.isoformat(),
                'records': {
                    'lessons': len(backup_data['lessons']),
                    'lesson_progress': len(backup_data['lesson_progress'])
                }
            }

            self._save_backup_metadata(backup_metadata)

            logger.info(f"Created incremental backup: {filename}")
            return backup_metadata

        except Exception as e:
            logger.error(f"Error creating incremental backup: {str(e)}")
            raise

    def restore_backup(self, backup_file: str, overwrite: bool = False,
                       restore_progress: bool = True) -> Dict[str, Any]:
        """
        Restore curriculum data from backup
        
        Args:
            backup_file: Path to backup file or backup ID
            overwrite: Whether to overwrite existing data
            restore_progress: Whether to restore progress data
            
        Returns:
            Restore summary
        """
        # Find backup file
        if not os.path.isabs(backup_file):
            # Treat as backup ID or filename
            backup_path = self._find_backup_file(backup_file)
        else:
            backup_path = backup_file

        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        try:
            # Load backup data
            backup_data = self._load_backup_file(backup_path)

            # Validate backup
            self._validate_backup_data(backup_data)

            # Create restore transaction
            restore_summary = {
                'backup_file': backup_path,
                'backup_id': backup_data['metadata']['backup_id'],
                'started_at': datetime.now(timezone.utc).isoformat(),
                'overwrite': overwrite,
                'restore_progress': restore_progress,
                'results': {}
            }

            with db.session.begin():
                # Restore CEFR levels
                if 'cefr_levels' in backup_data:
                    result = self._restore_cefr_levels(backup_data['cefr_levels'], overwrite)
                    restore_summary['results']['cefr_levels'] = result

                # Restore modules
                if 'modules' in backup_data:
                    result = self._restore_modules(backup_data['modules'], overwrite)
                    restore_summary['results']['modules'] = result

                # Restore lessons
                if 'lessons' in backup_data:
                    result = self._restore_lessons(backup_data['lessons'], overwrite)
                    restore_summary['results']['lessons'] = result

                # Restore progress (if requested)
                if restore_progress and 'lesson_progress' in backup_data:
                    result = self._restore_lesson_progress(backup_data['lesson_progress'], overwrite)
                    restore_summary['results']['lesson_progress'] = result

            restore_summary['completed_at'] = datetime.now(timezone.utc).isoformat()
            restore_summary['success'] = True

            logger.info(f"Restored backup: {backup_data['metadata']['backup_id']}")
            return restore_summary

        except Exception as e:
            logger.error(f"Error restoring backup: {str(e)}")
            restore_summary['error'] = str(e)
            restore_summary['success'] = False
            raise

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups"""
        backups = []
        metadata_file = os.path.join(self.backup_dir, 'backup_metadata.json')

        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    all_metadata = json.load(f)
                    backups = list(all_metadata.values())
            except Exception as e:
                logger.error(f"Error reading backup metadata: {str(e)}")

        # Also scan directory for backup files
        for filename in os.listdir(self.backup_dir):
            if filename.endswith('.json') or filename.endswith('.json.gz'):
                if filename == 'backup_metadata.json':
                    continue

                filepath = os.path.join(self.backup_dir, filename)

                # Check if already in metadata
                if any(b['filename'] == filename for b in backups):
                    continue

                # Add basic info
                stat = os.stat(filepath)
                backups.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size_bytes': stat.st_size,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    'metadata_missing': True
                })

        # Sort by creation date
        backups.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return backups

    def delete_backup(self, backup_identifier: str) -> bool:
        """Delete a backup file"""
        try:
            backup_path = self._find_backup_file(backup_identifier)
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)

                # Remove from metadata
                self._remove_backup_metadata(backup_identifier)

                logger.info(f"Deleted backup: {backup_identifier}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error deleting backup: {str(e)}")
            return False

    def cleanup_old_backups(self, keep_count: int = 10,
                            keep_days: int = 30) -> Dict[str, Any]:
        """Clean up old backup files"""
        backups = self.list_backups()

        # Sort by date
        backups.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        # Determine which backups to keep
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=keep_days)

        to_delete = []
        to_keep = []

        for i, backup in enumerate(backups):
            backup_date = datetime.fromisoformat(backup['created_at'].replace('Z', '+00:00'))

            if i < keep_count or backup_date > cutoff_date:
                to_keep.append(backup)
            else:
                to_delete.append(backup)

        # Delete old backups
        deleted_count = 0
        deleted_size = 0

        for backup in to_delete:
            if self.delete_backup(backup.get('backup_id', backup['filename'])):
                deleted_count += 1
                deleted_size += backup.get('size_bytes', 0)

        return {
            'deleted_count': deleted_count,
            'deleted_size_mb': round(deleted_size / (1024 * 1024), 2),
            'kept_count': len(to_keep),
            'cleanup_date': datetime.now(timezone.utc).isoformat()
        }

    def _export_cefr_levels(self) -> List[Dict]:
        """Export CEFR levels data"""
        levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
        return [{
            'id': level.id,
            'code': level.code,
            'name': level.name,
            'description': level.description,
            'order': level.order
        } for level in levels]

    def _export_modules(self) -> List[Dict]:
        """Export modules data"""
        modules = Module.query.order_by(Module.level_id, Module.number).all()
        return [{
            'id': module.id,
            'level_id': module.level_id,
            'number': module.number,
            'title': module.title,
            'description': module.description
        } for module in modules]

    def _export_lessons(self) -> List[Dict]:
        """Export lessons data"""
        lessons = Lessons.query.order_by(Lessons.module_id, Lessons.order, Lessons.number).all()
        return [{
            'id': lesson.id,
            'module_id': lesson.module_id,
            'number': lesson.number,
            'title': lesson.title,
            'type': lesson.type,
            'description': lesson.description,
            'content': lesson.content,
            'order': lesson.order
        } for lesson in lessons]

    def _export_lessons_since(self, since: datetime) -> List[Dict]:
        """Export lessons modified since specified date"""
        # For now, return all lessons as we don't have modified_at field
        # In production, you'd filter by modification date
        return self._export_lessons()

    def _export_lesson_progress(self) -> List[Dict]:
        """Export lesson progress data"""
        progress_records = LessonProgress.query.all()
        return [{
            'id': progress.id,
            'user_id': progress.user_id,
            'lesson_id': progress.lesson_id,
            'status': progress.status,
            'attempts': progress.attempts,
            'final_score': progress.final_score,
            'time_spent': progress.time_spent,
            'answers': progress.answers,
            'last_activity': progress.last_activity.isoformat() if progress.last_activity else None
        } for progress in progress_records]

    def _export_progress_since(self, since: datetime) -> List[Dict]:
        """Export progress records since specified date"""
        progress_records = LessonProgress.query.filter(
            LessonProgress.last_activity >= since
        ).all()

        return [{
            'id': progress.id,
            'user_id': progress.user_id,
            'lesson_id': progress.lesson_id,
            'status': progress.status,
            'attempts': progress.attempts,
            'final_score': progress.final_score,
            'time_spent': progress.time_spent,
            'answers': progress.answers,
            'last_activity': progress.last_activity.isoformat() if progress.last_activity else None
        } for progress in progress_records]

    def _load_backup_file(self, filepath: str) -> Dict:
        """Load backup data from file"""
        if filepath.endswith('.gz'):
            with gzip.open(filepath, 'rt', encoding='utf-8') as f:
                return json.load(f)
        else:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)

    def _validate_backup_data(self, data: Dict) -> None:
        """Validate backup data structure"""
        if 'metadata' not in data:
            raise ValueError("Invalid backup: missing metadata")

        metadata = data['metadata']
        required_fields = ['backup_id', 'created_at', 'version']

        for field in required_fields:
            if field not in metadata:
                raise ValueError(f"Invalid backup: missing metadata field '{field}'")

    def _restore_cefr_levels(self, levels_data: List[Dict], overwrite: bool) -> Dict:
        """Restore CEFR levels"""
        created = 0
        updated = 0
        skipped = 0

        for level_data in levels_data:
            existing = CEFRLevel.query.filter_by(code=level_data['code']).first()

            if existing:
                if overwrite:
                    existing.name = level_data['name']
                    existing.description = level_data['description']
                    existing.order = level_data['order']
                    updated += 1
                else:
                    skipped += 1
            else:
                level = CEFRLevel(
                    code=level_data['code'],
                    name=level_data['name'],
                    description=level_data['description'],
                    order=level_data['order']
                )
                db.session.add(level)
                created += 1

        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _restore_modules(self, modules_data: List[Dict], overwrite: bool) -> Dict:
        """Restore modules"""
        created = 0
        updated = 0
        skipped = 0

        for module_data in modules_data:
            existing = Module.query.filter_by(
                level_id=module_data['level_id'],
                number=module_data['number']
            ).first()

            if existing:
                if overwrite:
                    existing.title = module_data['title']
                    existing.description = module_data['description']
                    updated += 1
                else:
                    skipped += 1
            else:
                module = Module(
                    level_id=module_data['level_id'],
                    number=module_data['number'],
                    title=module_data['title'],
                    description=module_data['description']
                )
                db.session.add(module)
                created += 1

        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _restore_lessons(self, lessons_data: List[Dict], overwrite: bool) -> Dict:
        """Restore lessons"""
        created = 0
        updated = 0
        skipped = 0

        for lesson_data in lessons_data:
            existing = Lessons.query.filter_by(
                module_id=lesson_data['module_id'],
                number=lesson_data['number']
            ).first()

            if existing:
                if overwrite:
                    existing.title = lesson_data['title']
                    existing.type = lesson_data['type']
                    existing.description = lesson_data['description']
                    existing.content = lesson_data['content']
                    existing.order = lesson_data['order']
                    updated += 1
                else:
                    skipped += 1
            else:
                lesson = Lessons(
                    module_id=lesson_data['module_id'],
                    number=lesson_data['number'],
                    title=lesson_data['title'],
                    type=lesson_data['type'],
                    description=lesson_data['description'],
                    content=lesson_data['content'],
                    order=lesson_data['order']
                )
                db.session.add(lesson)
                created += 1

        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _restore_lesson_progress(self, progress_data: List[Dict], overwrite: bool) -> Dict:
        """Restore lesson progress"""
        created = 0
        updated = 0
        skipped = 0

        for progress_item in progress_data:
            existing = LessonProgress.query.filter_by(
                user_id=progress_item['user_id'],
                lesson_id=progress_item['lesson_id']
            ).first()

            if existing:
                if overwrite:
                    existing.status = progress_item['status']
                    existing.attempts = progress_item['attempts']
                    existing.final_score = progress_item['final_score']
                    existing.time_spent = progress_item['time_spent']
                    existing.answers = progress_item['answers']
                    if progress_item['last_activity']:
                        existing.last_activity = datetime.fromisoformat(progress_item['last_activity'])
                    updated += 1
                else:
                    skipped += 1
            else:
                progress = LessonProgress(
                    user_id=progress_item['user_id'],
                    lesson_id=progress_item['lesson_id'],
                    status=progress_item['status'],
                    attempts=progress_item['attempts'],
                    final_score=progress_item['final_score'],
                    time_spent=progress_item['time_spent'],
                    answers=progress_item['answers']
                )
                if progress_item['last_activity']:
                    progress.last_activity = datetime.fromisoformat(progress_item['last_activity'])
                db.session.add(progress)
                created += 1

        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _find_backup_file(self, identifier: str) -> Optional[str]:
        """Find backup file by ID or filename"""
        # Try as direct filename
        direct_path = os.path.join(self.backup_dir, identifier)
        if os.path.exists(direct_path):
            return direct_path

        # Try with extensions
        for ext in ['.json', '.json.gz']:
            path_with_ext = os.path.join(self.backup_dir, identifier + ext)
            if os.path.exists(path_with_ext):
                return path_with_ext

        # Try as backup ID
        for filename in os.listdir(self.backup_dir):
            if identifier in filename:
                return os.path.join(self.backup_dir, filename)

        return None

    def _save_backup_metadata(self, metadata: Dict) -> None:
        """Save backup metadata"""
        metadata_file = os.path.join(self.backup_dir, 'backup_metadata.json')

        # Load existing metadata
        all_metadata = {}
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    all_metadata = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load existing metadata: {str(e)}")

        # Add new metadata
        all_metadata[metadata['backup_id']] = metadata

        # Save updated metadata
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(all_metadata, f, ensure_ascii=False, indent=2)

    def _remove_backup_metadata(self, backup_id: str) -> None:
        """Remove backup metadata"""
        metadata_file = os.path.join(self.backup_dir, 'backup_metadata.json')

        if not os.path.exists(metadata_file):
            return

        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                all_metadata = json.load(f)

            if backup_id in all_metadata:
                del all_metadata[backup_id]

                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(all_metadata, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error removing backup metadata: {str(e)}")


class CurriculumMigrationManager:
    """Manager for curriculum data migrations"""

    def __init__(self, backup_manager: CurriculumBackupManager):
        self.backup_manager = backup_manager

    def export_for_migration(self, target_format: str = 'json') -> str:
        """Export curriculum data for migration to another system"""

        if target_format == 'json':
            return self._export_json_format()
        elif target_format == 'csv':
            return self._export_csv_format()
        elif target_format == 'xml':
            return self._export_xml_format()
        else:
            raise ValueError(f"Unsupported export format: {target_format}")

    def _export_json_format(self) -> str:
        """Export as JSON for API integration"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"curriculum_export_{timestamp}.json"

        # Create comprehensive export
        export_data = {
            'export_info': {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'format': 'json',
                'version': '1.0'
            },
            'curriculum': {
                'levels': self.backup_manager._export_cefr_levels(),
                'modules': self.backup_manager._export_modules(),
                'lessons': self.backup_manager._export_lessons()
            }
        }

        export_path = os.path.join(self.backup_manager.backup_dir, filename)
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Created JSON export: {filename}")
        return export_path

    def _export_csv_format(self) -> str:
        """Export as CSV files for spreadsheet import"""
        import csv

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        export_dir = os.path.join(self.backup_manager.backup_dir, f"csv_export_{timestamp}")
        os.makedirs(export_dir, exist_ok=True)

        # Export levels
        levels_file = os.path.join(export_dir, 'cefr_levels.csv')
        with open(levels_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'code', 'name', 'description', 'order'])
            writer.writeheader()
            writer.writerows(self.backup_manager._export_cefr_levels())

        # Export modules
        modules_file = os.path.join(export_dir, 'modules.csv')
        with open(modules_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'level_id', 'number', 'title', 'description'])
            writer.writeheader()
            writer.writerows(self.backup_manager._export_modules())

        # Export lessons
        lessons_file = os.path.join(export_dir, 'lessons.csv')
        lessons_data = self.backup_manager._export_lessons()

        # Convert content to string for CSV
        for lesson in lessons_data:
            if isinstance(lesson['content'], dict):
                lesson['content'] = json.dumps(lesson['content'], ensure_ascii=False)

        with open(lessons_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'module_id', 'number', 'title', 'type',
                                                   'description', 'content', 'order'])
            writer.writeheader()
            writer.writerows(lessons_data)

        logger.info(f"Created CSV export: {export_dir}")
        return export_dir

    def _export_xml_format(self) -> str:
        """Export as XML for system integration"""
        import xml.etree.ElementTree as ET

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"curriculum_export_{timestamp}.xml"

        # Create XML structure
        root = ET.Element('curriculum_export')
        root.set('created_at', datetime.now(timezone.utc).isoformat())
        root.set('version', '1.0')

        # Add levels
        levels_elem = ET.SubElement(root, 'cefr_levels')
        for level in self.backup_manager._export_cefr_levels():
            level_elem = ET.SubElement(levels_elem, 'level')
            for key, value in level.items():
                level_elem.set(str(key), str(value))

        # Add modules
        modules_elem = ET.SubElement(root, 'modules')
        for module in self.backup_manager._export_modules():
            module_elem = ET.SubElement(modules_elem, 'module')
            for key, value in module.items():
                if key != 'description':
                    module_elem.set(str(key), str(value))
                else:
                    desc_elem = ET.SubElement(module_elem, 'description')
                    desc_elem.text = str(value)

        # Add lessons
        lessons_elem = ET.SubElement(root, 'lessons')
        for lesson in self.backup_manager._export_lessons():
            lesson_elem = ET.SubElement(lessons_elem, 'lesson')
            for key, value in lesson.items():
                if key in ['description', 'content']:
                    child_elem = ET.SubElement(lesson_elem, key)
                    if isinstance(value, dict):
                        child_elem.text = json.dumps(value, ensure_ascii=False)
                    else:
                        child_elem.text = str(value)
                else:
                    lesson_elem.set(str(key), str(value))

        # Save XML
        tree = ET.ElementTree(root)
        export_path = os.path.join(self.backup_manager.backup_dir, filename)
        tree.write(export_path, encoding='utf-8', xml_declaration=True)

        logger.info(f"Created XML export: {filename}")
        return export_path


# Global instances (will be initialized in init_backup_system)
backup_manager = None
migration_manager = None


def init_backup_system(app):
    """Initialize backup system"""
    global backup_manager, migration_manager

    # Initialize global instances with app context
    backup_manager = CurriculumBackupManager()
    migration_manager = CurriculumMigrationManager(backup_manager)

    @app.route('/curriculum/admin/backup/create', methods=['POST'])
    def create_backup():
        """Create curriculum backup (admin only)"""
        from flask import request, current_user

        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        data = request.get_json() or {}
        include_progress = data.get('include_progress', True)
        compress = data.get('compress', True)

        try:
            backup_metadata = backup_manager.create_full_backup(include_progress, compress)
            return {'success': True, 'backup': backup_metadata}
        except Exception as e:
            return {'success': False, 'error': str(e)}, 500

    @app.route('/curriculum/admin/backup/list')
    def list_backups():
        """List available backups (admin only)"""
        from flask import current_user

        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        try:
            backups = backup_manager.list_backups()
            return {'backups': backups}
        except Exception as e:
            return {'error': str(e)}, 500

    @app.route('/curriculum/admin/backup/restore', methods=['POST'])
    def restore_backup():
        """Restore from backup (admin only)"""
        from flask import request, current_user

        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        data = request.get_json() or {}
        backup_id = data.get('backup_id')
        overwrite = data.get('overwrite', False)
        restore_progress = data.get('restore_progress', True)

        if not backup_id:
            return {'error': 'backup_id is required'}, 400

        try:
            restore_summary = backup_manager.restore_backup(backup_id, overwrite, restore_progress)
            return {'success': True, 'restore': restore_summary}
        except Exception as e:
            return {'success': False, 'error': str(e)}, 500

    @app.route('/curriculum/admin/backup/cleanup', methods=['POST'])
    def cleanup_backups():
        """Clean up old backups (admin only)"""
        from flask import request, current_user

        if not current_user.is_authenticated or not current_user.is_admin:
            return {'error': 'Admin access required'}, 403

        data = request.get_json() or {}
        keep_count = data.get('keep_count', 10)
        keep_days = data.get('keep_days', 30)

        try:
            cleanup_result = backup_manager.cleanup_old_backups(keep_count, keep_days)
            return {'success': True, 'cleanup': cleanup_result}
        except Exception as e:
            return {'success': False, 'error': str(e)}, 500

    logger.info("Initialized curriculum backup system")
