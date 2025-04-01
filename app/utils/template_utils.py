import copy

from flask import request


def url_params_with_updated_args(**updates):
    """
    Generate a dictionary of URL parameters based on current request args,
    but with specified parameters updated or removed.

    Usage in template:
    {{ url_for('endpoint', **url_params(page=2, sort='name')) }}

    Args:
        **updates: Parameters to update. Use None to remove a parameter.

    Returns:
        dict: Updated URL parameters
    """
    args = copy.deepcopy(request.args.to_dict(flat=True))

    # Update/add parameters
    for key, value in updates.items():
        if value is None:
            # Remove parameter if value is None
            if key in args:
                del args[key]
        else:
            # Add or update parameter
            args[key] = str(value)  # Convert values to strings for URL parameters

    return args


def init_template_utils(app):
    """
    Register template utility functions with the Flask app.

    Args:
        app: Flask application instance
    """

    @app.context_processor
    def utility_processor():
        return {
            'url_params': url_params_with_updated_args
        }
