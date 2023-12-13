from flask import Flask
from .v1.umami import umami_blueprint
from .v1.umami.menu import menu_blueprint

def create_app():
    app = Flask(__name__)

    # Register the main Umami blueprint
    app.register_blueprint(umami_blueprint, url_prefix='/api/v1/umami')

    # Register the Menu blueprint as a sub-route of Umami
    app.register_blueprint(menu_blueprint, url_prefix='/api/v1/umami/menu')

    return app
