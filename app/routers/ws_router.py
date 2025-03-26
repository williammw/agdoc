from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging
import json
from typing import Dict, List, Any

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active connections for users
connections: Dict[str, WebSocket] = {}

# Store active conversation connections
conversation_connections: Dict[str, List[WebSocket]] = {}

async def broadcast(message: dict, exclude: str = None):
    for user_id, connection in connections.items():
        if user_id != exclude:
            await connection.send_text(json.dumps(message))

async def broadcast_to_conversation(conversation_id: str, message: Dict[str, Any]):
    """Broadcast a message to all WebSocket clients for a specific conversation"""
    if conversation_id in conversation_connections:
        disconnected = []
        for connection in conversation_connections[conversation_id]:
            try:
                await connection.send_text(json.dumps(message))
                logger.info(f"Sent update to conversation {conversation_id}: {message['type']}")
            except Exception as e:
                logger.error(f"Error sending websocket message: {str(e)}")
                disconnected.append(connection)
        
        # Clean up any disconnected clients
        for conn in disconnected:
            if conn in conversation_connections[conversation_id]:
                conversation_connections[conversation_id].remove(conn)
        
        if not conversation_connections[conversation_id]:
            del conversation_connections[conversation_id]

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
        if user_id in connections:
            del connections[user_id]

@router.websocket("/conversation/{conversation_id}")
async def conversation_websocket(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    
    # Add this connection to active conversation connections
    if conversation_id not in conversation_connections:
        conversation_connections[conversation_id] = []
    conversation_connections[conversation_id].append(websocket)
    
    logger.info(f"WebSocket connection accepted for conversation {conversation_id}")
    
    try:
        # Keep the connection alive
        while True:
            # Wait for any client messages
            data = await websocket.receive_text()
            
            # Handle ping messages with pong responses to keep the connection alive
            try:
                message = json.loads(data)
                if message.get('type') == 'ping':
                    await websocket.send_text(json.dumps({'type': 'pong'}))
            except Exception as e:
                # If not valid JSON or other error, just ignore it
                pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for conversation {conversation_id}")
        if conversation_id in conversation_connections and websocket in conversation_connections[conversation_id]:
            conversation_connections[conversation_id].remove(websocket)
            if not conversation_connections[conversation_id]:
                del conversation_connections[conversation_id]
    except Exception as e:
        logger.error(f"An error occurred for conversation {conversation_id}: {e}")
        if conversation_id in conversation_connections and websocket in conversation_connections[conversation_id]:
            conversation_connections[conversation_id].remove(websocket)
