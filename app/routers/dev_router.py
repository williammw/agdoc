from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
from databases import Database
from app.dependencies import get_database


router = APIRouter()


class Item(BaseModel):
    id: int
    name: str
    description: str

# In-memory database simulation
items = {}


@router.get("/items/")
async def read_items(database=Depends(get_database)):
    query = "SELECT * FROM items"  # Assuming an 'items' table exists
    return await database.fetch_all(query)

# Create an item
@router.post("/items/")
def create_item(item: Item):
    if item.id in items:
        raise HTTPException(status_code=400, detail="Item already exists")
    items[item.id] = item
    return items[item.id]

# Read an item


@router.get("/items/{item_id}")
def read_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return items[item_id]

# Update an item


@router.put("/items/{item_id}")
def update_item(item_id: int, item: Item):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    items[item_id] = item
    return items[item_id]

# Delete an item


@router.delete("/items/{item_id}")
def delete_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    del items[item_id]
    return {"message": "Item deleted successfully"}
