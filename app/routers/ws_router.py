from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging
import json
from typing import Dict

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active connections
connections: Dict[str, WebSocket] = {}

async def broadcast(message: dict, exclude: str = None):
    for user_id, connection in connections.items():
        if user_id != exclude:
            await connection.send_text(json.dumps(message))

@router.websocket("/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    connections[user_id] = websocket
    logger.info(f"WebSocket connection accepted for user {user_id}")

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"Received message from {user_id}: {message}")

            if message['type'] == 'offer':
                # Forward the offer to the specified peer
                await connections[message['target']].send_text(json.dumps({
                    'type': 'offer',
                    'offer': message['offer'],
                    'from': user_id
                }))

            elif message['type'] == 'answer':
                # Forward the answer to the specified peer
                await connections[message['target']].send_text(json.dumps({
                    'type': 'answer',
                    'answer': message['answer'],
                    'from': user_id
                }))

            elif message['type'] == 'ice-candidate':
                # Forward the ICE candidate to the specified peer
                await connections[message['target']].send_text(json.dumps({
                    'type': 'ice-candidate',
                    'candidate': message['candidate'],
                    'from': user_id
                }))

            elif message['type'] == 'join':
                # Notify all users about the new user
                await broadcast({
                    'type': 'user-joined',
                    'user_id': user_id
                }, exclude=user_id)

            elif message['type'] == 'leave':
                # Notify all users about the leaving user
                await broadcast({
                    'type': 'user-left',
                    'user_id': user_id
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for user {user_id}")
        del connections[user_id]
        await broadcast({
            'type': 'user-left',
            'user_id': user_id
        })
    except Exception as e:
        logger.error(f"An error occurred for user {user_id}: {e}")
        del connections[user_id]
