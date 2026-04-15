import os

from app import create_app
from cli import translate

app = create_app()
app.cli.add_command(translate)

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
