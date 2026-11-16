"""Read-only course catalogue, using the same access rules as the website."""

from flask import Blueprint
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response

api_native_catalog = Blueprint("api_native_catalog", __name__)
api_native_catalog.after_request(private_response)
api_native_catalog.register_error_handler(NativeLessonError, native_error)


@api_native_catalog.get("/courses")
@api_bearer_required
def courses():
    from app.curriculum.routes.api import api_get_levels

    return api_get_levels()


@api_native_catalog.get("/courses/<level>/modules")
@api_bearer_required
def modules(level):
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.curriculum.routes.api import api_get_level_modules

    if level not in PUBLIC_CEFR_CODES:
        raise NativeLessonError("not_found", 404)
    return api_get_level_modules(level)


@api_native_catalog.get("/modules/<int:module_id>/lessons")
@api_bearer_required
def lessons(module_id):
    from app.curriculum.routes.api import api_get_module_lessons

    return api_get_module_lessons(module_id)
