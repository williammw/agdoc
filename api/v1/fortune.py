from flask import Blueprint

fortune_blueprint = Blueprint('fortune', __name__)


@fortune_blueprint.route('/menu', methods=['GET'])
def fortune_menu():
    return 'Fortune Telling menu route'

