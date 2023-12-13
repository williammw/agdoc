# File: real_world_app/api/v1/umami/menu.py
from flask import Blueprint, jsonify, request, Response

menu_blueprint = Blueprint('menu', __name__)

# Example data structure for menu items
menu_items = [
    {"id": 1, "name": "Sushi", "description": "Fresh sushi platter"},
    {"id": 2, "name": "Ramen", "description": "Delicious ramen bowl"}
]

# Route to get all menu items
@menu_blueprint.route('/', methods=['GET'])
def get_menu_items():
    return jsonify(menu_items)

# Route to add a new menu item
@menu_blueprint.route('/', methods=['POST'])
def add_menu_item():
    new_item = request.json
    menu_items.append(new_item)
    return Response("Menu item added", status=201)

# Route to get a specific menu item by ID
@menu_blueprint.route('/<int:item_id>', methods=['GET'])
def get_menu_item(item_id):
    item = next((item for item in menu_items if item["id"] == item_id), None)
    if item:
        return jsonify(item)
    return Response("Item not found", status=404)

# Additional routes can be added here for updating or deleting menu items
