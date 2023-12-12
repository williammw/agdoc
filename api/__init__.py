from flask import Flask
from .v1.umami import umami_blueprint
from .v1.fortune import fortune_blueprint


def create_app():
    app = Flask(__name__)

    # Other configurations...

    app.register_blueprint(umami_blueprint, url_prefix='/api/v1/umami')
    app.register_blueprint(fortune_blueprint, url_prefix='/api/v1/fortune')

    return app
