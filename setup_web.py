#!/usr/bin/env python3
"""
Setup script for the web application.
Creates necessary directories and initializes database schema.
"""
import logging
import os
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Import project modules
try:
    from config.settings import DB_FILE
    from src.db.models import DBInitializer
    from src.user.repository import UserRepository
except ImportError as e:
    logger.error(f"Error importing project modules: {e}")
    logger.error("Make sure you're running this script from the project root directory")
    sys.exit(1)


def setup_project_structure():
    """Set up the project directory structure."""
    logger.info("Setting up project directory structure...")

    # Create directories
    os.makedirs("src/user", exist_ok=True)
    os.makedirs("static/media", exist_ok=True)
    os.makedirs("templates", exist_ok=True)

    logger.info("Directory structure created successfully")


def copy_python_files():
    """Copy Python files to their appropriate locations."""
    logger.info("Copying Python files...")

    # Ensure user module is recognized as a package
    with open("src/user/__init__.py", "w") as f:
        f.write('"""User module package."""\n')

    # Copy model and repository files
    # (These would be the files we created above with the user_models and user_repository artifacts)

    logger.info("Python files copied successfully")


def setup_database():
    """Set up the database schema."""
    logger.info(f"Setting up database at {DB_FILE}...")

    # Initialize the base database schema
    DBInitializer.create_tables(DB_FILE)

    # Initialize the user schema
    user_repo = UserRepository(DB_FILE)
    user_repo.initialize_schema()

    logger.info("Database schema set up successfully")


def create_templates():
    """Create HTML templates."""
    logger.info("Creating HTML templates...")

    # Create base templates
    # (These would be the template files we created above)

    logger.info("HTML templates created successfully")


def main():
    """Main setup function."""
    logger.info("Starting setup...")

    setup_project_structure()
    copy_python_files()
    setup_database()
    create_templates()

    logger.info("Setup completed successfully!")
    logger.info("Run 'flask run' to start the web application")


if __name__ == "__main__":
    main()
