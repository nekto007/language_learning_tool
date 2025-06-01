# app/curriculum/security.py

import re
from functools import wraps
from typing import Any, Dict, List, Optional, Union

import bleach
from flask import abort
from flask_login import current_user
from markupsafe import escape

from app.curriculum.models import LessonProgress, Lessons, Module

# Allowed HTML tags for content sanitization
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li',
    'blockquote', 'code', 'pre', 'h3', 'h4', 'h5', 'h6',
    'a', 'span', 'div'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title'],
    'span': ['class'],
    'div': ['class'],
}


def sanitize_html(text: str) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.
    
    Args:
        text: Raw HTML string
        
    Returns:
        Sanitized HTML string
    """
    if not text:
        return ""

    # Clean the HTML
    cleaned = bleach.clean(
        text,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )

    # Additional cleanup for javascript: and other dangerous protocols
    cleaned = re.sub(r'javascript:', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'on\w+\s*=', '', cleaned, flags=re.IGNORECASE)

    return cleaned


def sanitize_json_content(content: Union[Dict, List, Any]) -> Union[Dict, List, Any]:
    """
    Recursively sanitize JSON content for safe storage and display.
    
    Args:
        content: JSON-serializable content
        
    Returns:
        Sanitized content
    """
    if isinstance(content, dict):
        return {
            key: sanitize_json_content(value)
            for key, value in content.items()
        }
    elif isinstance(content, list):
        return [sanitize_json_content(item) for item in content]
    elif isinstance(content, str):
        # For regular strings, escape HTML
        return escape(content)
    else:
        return content


def validate_lesson_content(lesson_type: str, content: Dict) -> tuple[bool, Optional[str]]:
    """
    Validate lesson content structure based on lesson type.
    
    Args:
        lesson_type: Type of lesson (vocabulary, grammar, quiz, etc.)
        content: Lesson content dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(content, dict) and not isinstance(content, list):
        return False, "Content must be a dictionary or list"

    if lesson_type == 'vocabulary':
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    return False, "Vocabulary items must be dictionaries"
                if 'word' not in item and 'front' not in item:
                    return False, "Vocabulary items must have 'word' or 'front' field"
        elif 'words' not in content and 'items' not in content:
            return False, "Vocabulary content must have 'words' or 'items' field"

    elif lesson_type == 'grammar':
        required_fields = ['title', 'content']
        for field in required_fields:
            if field not in content:
                return False, f"Grammar content must have '{field}' field"

    elif lesson_type == 'quiz':
        if 'questions' not in content:
            return False, "Quiz content must have 'questions' field"

        questions = content.get('questions', [])
        if not isinstance(questions, list):
            return False, "Questions must be a list"

        for i, question in enumerate(questions):
            if not isinstance(question, dict):
                return False, f"Question {i + 1} must be a dictionary"
            if 'question' not in question:
                return False, f"Question {i + 1} must have 'question' field"
            if 'options' not in question or not isinstance(question['options'], list):
                return False, f"Question {i + 1} must have 'options' list"
            if 'correct' not in question:
                return False, f"Question {i + 1} must have 'correct' field"

    elif lesson_type == 'matching':
        if 'pairs' not in content:
            return False, "Matching content must have 'pairs' field"

        pairs = content.get('pairs', [])
        if not isinstance(pairs, list):
            return False, "Pairs must be a list"

        for i, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                return False, f"Pair {i + 1} must be a dictionary"
            if 'left' not in pair or 'right' not in pair:
                return False, f"Pair {i + 1} must have 'left' and 'right' fields"

    elif lesson_type == 'text':
        if 'content' not in content and 'text' not in content:
            return False, "Text lesson must have 'content' or 'text' field"

    elif lesson_type == 'card':
        # Card lessons can have various structures
        pass

    return True, None


def check_lesson_access(lesson_id: int) -> bool:
    """
    Check if current user has access to a lesson.
    
    Args:
        lesson_id: ID of the lesson to check
        
    Returns:
        True if user has access, False otherwise
    """
    if not current_user.is_authenticated:
        return False

    # Admins have access to all lessons
    if current_user.is_admin:
        return True

    # Get the lesson
    lesson = Lessons.query.get(lesson_id)
    if not lesson:
        return False

    # Check if user has started any lesson in this module
    module_progress = LessonProgress.query.filter_by(
        user_id=current_user.id
    ).join(Lessons).filter(
        Lessons.module_id == lesson.module_id
    ).first()

    # If user has progress in this module, they can access it
    if module_progress:
        return True

    # Check if this is the first lesson of the first module in a level
    module = Module.query.get(lesson.module_id)
    if not module:
        return False

    # Get first module in this level
    first_module = Module.query.filter_by(
        level_id=module.level_id
    ).order_by(Module.number).first()

    # If this is the first module
    if module.id == first_module.id:
        # Check if this is the first lesson
        first_lesson = Lessons.query.filter_by(
            module_id=module.id
        ).order_by(Lessons.number).first()

        if lesson.id == first_lesson.id:
            return True

    return False


def check_module_access(module_id: int) -> bool:
    """
    Check if current user has access to a module.
    
    Args:
        module_id: ID of the module to check
        
    Returns:
        True if user has access, False otherwise
    """
    if not current_user.is_authenticated:
        return False

    # Admins have access to all modules
    if current_user.is_admin:
        return True

    # Get the module
    module = Module.query.get(module_id)
    if not module:
        return False

    # Check if user has started any lesson in this module
    module_progress = LessonProgress.query.filter_by(
        user_id=current_user.id
    ).join(Lessons).filter(
        Lessons.module_id == module_id
    ).first()

    # If user has progress in this module, they can access it
    if module_progress:
        return True

    # Check if this is the first module in a level
    first_module = Module.query.filter_by(
        level_id=module.level_id
    ).order_by(Module.number).first()

    if module.id == first_module.id:
        return True

    # Check if user has completed previous module (80% threshold)
    if module.number > 1:
        prev_module = Module.query.filter_by(
            level_id=module.level_id,
            number=module.number - 1
        ).first()

        if prev_module:
            # Check completion percentage of previous module
            from sqlalchemy import func
            
            total_lessons = Lessons.query.filter_by(module_id=prev_module.id).count()
            completed_count = LessonProgress.query.filter_by(
                user_id=current_user.id,
                status='completed'
            ).join(Lessons).filter(
                Lessons.module_id == prev_module.id
            ).count()

            completion_percentage = (completed_count / total_lessons * 100) if total_lessons > 0 else 0
            
            # Require 80% completion to unlock next module
            if completion_percentage >= 80:
                return True

    return False


def require_lesson_access(f):
    """
    Decorator to check lesson access permissions.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        lesson_id = kwargs.get('lesson_id')
        if not lesson_id:
            abort(400, "Lesson ID is required")

        if not check_lesson_access(lesson_id):
            abort(403, "You don't have access to this lesson")

        return f(*args, **kwargs)

    return decorated_function


def require_module_access(f):
    """
    Decorator to check module access permissions.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        module_id = kwargs.get('module_id')
        if not module_id:
            abort(400, "Module ID is required")

        if not check_module_access(module_id):
            abort(403, "You don't have access to this module")

        return f(*args, **kwargs)

    return decorated_function


def validate_file_upload(file, max_size_mb: int = 10, allowed_extensions: set = None) -> tuple[bool, Optional[str]]:
    """
    Validate uploaded file for security.
    
    Args:
        file: FileStorage object
        max_size_mb: Maximum file size in MB
        allowed_extensions: Set of allowed file extensions
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not file:
        return False, "No file provided"

    # Check file size
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning

    if file_size > max_size_mb * 1024 * 1024:
        return False, f"File size exceeds {max_size_mb}MB limit"

    # Check file extension
    if allowed_extensions:
        filename = file.filename
        if not filename:
            return False, "File has no filename"

        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if ext not in allowed_extensions:
            return False, f"File type .{ext} is not allowed. Allowed types: {', '.join(allowed_extensions)}"

    # Check for potential malicious content in filename
    if file.filename:
        # Remove any path components
        safe_filename = file.filename.rsplit('/', 1)[-1]
        safe_filename = safe_filename.rsplit('\\', 1)[-1]

        # Check for suspicious patterns
        suspicious_patterns = [
            '..',  # Directory traversal
            '<', '>',  # HTML tags
            'script',  # JavaScript
            '.exe', '.bat', '.cmd',  # Executables
        ]

        for pattern in suspicious_patterns:
            if pattern in safe_filename.lower():
                return False, f"Filename contains suspicious pattern: {pattern}"

    return True, None


def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert value to integer.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
        
    Returns:
        Integer value
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safely convert value to float.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
        
    Returns:
        Float value
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
