#dev_router.py
import random
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends 
from databases import Database
from app.dependencies import get_database
from fastapi import FastAPI, Request
from pydantic import BaseModel
from bs4 import BeautifulSoup
import random


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

# citi today 4482
# 


class TextInput(BaseModel):
    text: str


def introduce_grammar_mistakes(text: str) -> str:
    text = text.replace(", and", " and").replace(" it's", " its")
    return text


def add_personal_touches(text: str) -> str:
    personal_phrases = [
        "I guess, ",
        "you know, ",
        "I think that ",
        "To be honest, "
    ]
    sentences = text.split(". ")
    for i in range(len(sentences)):
        if random.random() < 0.3:
            sentences[i] = random.choice(
                personal_phrases) + sentences[i].strip()
    return ". ".join(sentences)


def vary_vocabulary(text: str) -> str:
    text = text.replace("use", "utilize").replace("make", "create")
    return text


def inject_emotion(text: str) -> str:
    emotions = ["amazing", "frustrating", "exciting", "terrifying"]
    text = text.replace("interesting", random.choice(emotions))
    return text


def add_informal_language(text: str) -> str:
    informal_phrases = [
        "like, ",
        "kind of, ",
        "sort of, ",
        "basically, "
    ]
    sentences = text.split(". ")
    for i in range(len(sentences)):
        if random.random() < 0.2:
            sentences[i] = informal_phrases[random.randint(
                0, len(informal_phrases) - 1)] + sentences[i].strip()
    return ". ".join(sentences)


def humanize_text(text: str) -> str:
    text = introduce_grammar_mistakes(text)
    text = add_personal_touches(text)
    text = vary_vocabulary(text)
    text = inject_emotion(text)
    text = add_informal_language(text)
    return text


def process_html_content(html_content: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')

    # Traverse and humanize text in all text nodes
    for element in soup.find_all(text=True):
        if element.parent.name not in ['style', 'script', '[document]', 'head', 'title']:
            humanized_text = humanize_text(element.string)
            element.replace_with(humanized_text)

    return str(soup)


@router.post("/humanize")
async def humanize(request: TextInput):
    original_text = request.text

    if "<" in original_text and ">" in original_text:
        # Treat the text as HTML
        humanized_text = process_html_content(original_text)
    else:
        # Treat the text as plain text
        humanized_text = humanize_text(original_text)

    return {"original_text": original_text, "humanized_text": humanized_text}
