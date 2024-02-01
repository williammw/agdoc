from flask import Flask
from .v1.umami import umami_blueprint
from .v1.umami.menu import menu_blueprint
from .v1.fortune import fortune_blueprint
from .v1.fortune.menu import fortune_menu_blueprint
from .v1.fortune.base import fortune_base_blueprint
from .v1.asr.base import asr_blueprint


def create_app():
    app = Flask(__name__)

    # Register the main Umami blueprint
    app.register_blueprint(umami_blueprint, url_prefix='/api/v1/umami')

    # Register the Menu blueprint as a sub-route of Umami
    app.register_blueprint(menu_blueprint, url_prefix='/api/v1/umami/menu')

    # Register the ASR blueprint
    app.register_blueprint(asr_blueprint, url_prefix='/api/v1/asr')

    # fortune
    app.register_blueprint(fortune_blueprint, url_prefix='/api/v1/fortune')
    app.register_blueprint(fortune_menu_blueprint,
                           url_prefix='/api/v1/fortune/menu')

    app.register_blueprint(
        fortune_base_blueprint, url_prefix='/api/v1/fortune/base')

    return app
