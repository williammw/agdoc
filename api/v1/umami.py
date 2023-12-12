from flask import Blueprint

umami_blueprint = Blueprint('umami', __name__)


@umami_blueprint.route('/menu', methods=['GET', 'POST'])
def umami_menu():
    return 'Umami menu route'
