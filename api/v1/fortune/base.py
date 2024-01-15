from flask import Blueprint, jsonify

fortune_base_blueprint = Blueprint('fortune_base', __name__)


@fortune_base_blueprint.route('/', methods=['GET'])
def get_fortune_items():
    return '甲斐田さん、おはようございます。'
