from flask import Blueprint, jsonify

fortune_base_blueprint = Blueprint('fortune_base', __name__)

tenkan = {
    0: '甲',
    1: '乙',
    2: '丙',
    3: '丁',
    4: '戊',
    5: '己',
    6: '庚',
    7: '辛',
    8: '壬',
    9: '癸'
}

zodiac = {
    0: '子',
    1: '丑',
    2: '寅',
    3: '卯',
    4: '辰',
    5: '巳',
    6: '午',
    7: '未',
    8: '申',
    9: '酉',
    10: '戌',
    11: '亥'
}


@fortune_base_blueprint.route('/', methods=['GET'])
def get_fortune_items():
    return '甲斐田さん、おはようございます。'
