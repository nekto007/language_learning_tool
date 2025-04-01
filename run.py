from app import create_app
from cli import translate
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
    app.cli.add_command(translate)