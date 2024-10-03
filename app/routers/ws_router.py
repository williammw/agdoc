from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import openai
import os
router = APIRouter()

# Set up your OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Store active connections
connections = []


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    try:
        while True:
            # Receive message from frontend
            data = await websocket.receive_text()

            # Process message with OpenAI
            response = openai.Completion.create(
                engine="davinci",
                prompt=data,
                max_tokens=50
            )

            # Extract text from OpenAI response
            message = response.choices[0].text.strip()

            # Send response back to the frontend
            await websocket.send_text(message)
    except WebSocketDisconnect:
        connections.remove(websocket)
        await websocket.close()
