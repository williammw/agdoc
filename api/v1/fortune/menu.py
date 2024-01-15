# File: real_world_app/api/v1/fortune.py
from flask import Blueprint, jsonify, request, Response

fortune_menu_blueprint = Blueprint('fortune_menu', __name__)

# Example data structure for fortune items
fortune_items = [
    {"id": 1, "name": "Fortune", "description": "AAAAFresh sushi platter"},
    {"id": 2, "name": "NewTon", "description": "BBBBDelicious ramen bowl"}
]

# Route to get all fortune items


@fortune_menu_blueprint.route('/', methods=['GET'])
def get_fortune_items():
    return jsonify(fortune_items)

# Route to add a new fortune item


@fortune_menu_blueprint.route('/', methods=['POST'])
def add_fortune_item():
    new_item = request.json
    fortune_items.append(new_item)
    return Response("fortune item added", status=201)

# Route to get a specific fortune item by ID


@fortune_menu_blueprint.route('/<int:item_id>', methods=['GET'])
def get_fortune_item(item_id):
    item = next(
        (item for item in fortune_items if item["id"] == item_id), None)
    if item:
        return jsonify(item)
    return Response("Item not found", status=404)

# Additional routes can be added here for updating or deleting fortune items
