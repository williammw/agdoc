from flask import Blueprint, jsonify, request
from dotenv import load_dotenv

import os

load_dotenv()

asr_blueprint = Blueprint('asr', __name__)


# @asr_blueprint.route('/', methods=['GET'])
# def landing():
#     return 'This is asr entry point'

# using open ai api here


@asr_blueprint.route('/', methods=['GET'])
def greeting():
    user = request.args.get('user', 'Guest')
    testapi = os.getenv('TEST_API')
    return f'{user},  welcome to asr ; your test api is {testapi}'
