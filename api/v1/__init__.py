from .fortune import fortune_blueprint
from .umami import umami_blueprint
from flask import Blueprint

v1_blueprint = Blueprint('v1', __name__)


# v1_blueprint.register_blueprint(umami_blueprint, url_prefix='/umami')
# v1_blueprint.register_blueprint(fortune_blueprint, url_prefix='/fortune')
