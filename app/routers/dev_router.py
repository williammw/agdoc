#dev_router.py
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
@router.post("/items/", response_model=Item)
async def create_item(item: Item, database: Database = Depends(get_database)):
    query = "INSERT INTO items(id, name, description) VALUES (:id, :name, :description) RETURNING *"
    values = {"id": item.id, "name": item.name,
            "description": item.description}
    try:
        result = await database.execute(query=query, values=values)
        return await database.fetch_one("SELECT * FROM items WHERE id = :id", {"id": result})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Read an item

@router.get("/items/{item_id}", response_model=Item)
async def read_item(item_id: int, database: Database = Depends(get_database)):
    query = "SELECT * FROM items WHERE id = :id"
    result = await database.fetch_one(query, values={"id": item_id})
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result

# Update an item


@router.put("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, item: Item, database: Database = Depends(get_database)):
    check_query = "SELECT * FROM items WHERE id = :id"
    check_item = await database.fetch_one(check_query, values={"id": item_id})
    if check_item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    update_query = """
    UPDATE items
    SET name = :name, description = :description
    WHERE id = :id
    RETURNING *;
    """
    updated_item = await database.fetch_one(update_query, values={"id": item_id, "name": item.name, "description": item.description})
    return updated_item

# Delete an item


@router.delete("/items/{item_id}", response_model=dict)
async def delete_item(item_id: int, database: Database = Depends(get_database)):
    check_query = "SELECT * FROM items WHERE id = :id"
    check_item = await database.fetch_one(check_query, values={"id": item_id})
    if check_item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    delete_query = "DELETE FROM items WHERE id = :id"
    await database.execute(delete_query, values={"id": item_id})
    return {"message": "Item deleted successfully"}
