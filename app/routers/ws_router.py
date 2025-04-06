from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
import logging
import json
import time
from typing import Dict, List, Any

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active connections for users
connections: Dict[str, WebSocket] = {}

# Store active conversation connections with timestamp for debugging
conversation_connections: Dict[str, List[dict]] = {}

async def broadcast(message: dict, exclude: str = None):
    for user_id, connection in connections.items():
        if user_id != exclude:
            await connection.send_text(json.dumps(message))

async def broadcast_to_conversation(conversation_id: str, message: Dict[str, Any]):
    """Broadcast a message to all WebSocket clients for a specific conversation"""
    if conversation_id in conversation_connections:
        disconnected = []
        success_count = 0
        
        logger.info(f"Broadcasting to conversation {conversation_id}: {message['type']}")
        
        # Log message details based on type
        if message['type'] == 'message_update' and 'updates' in message:
            has_image = 'imageUrl' in message['updates']
            image_status = message['updates'].get('status', 'unknown')
            logger.info(f"Message update for {message.get('messageId', 'unknown')}: hasImage={has_image}, status={image_status}")
            
            # For image updates, log more details
            if has_image:
                image_url = message['updates']['imageUrl']
                truncated_url = image_url[:40] + '...' if len(image_url) > 40 else image_url
                logger.info(f"Image update: url={truncated_url}")
        
        for conn_info in conversation_connections[conversation_id]:
            try:
                # Send the message as stringified JSON
                message_text = json.dumps(message)
                await conn_info["connection"].send_text(message_text)
                success_count += 1
                
                # Log success but only for types we're interested in
                if message['type'] != 'ping' and message['type'] != 'pong':
                    logger.info(f"Successfully sent {message['type']} to a client for conversation {conversation_id}")
            except Exception as e:
                logger.error(f"Error sending websocket message: {str(e)}")
                disconnected.append(conn_info)
        
        # Log summary of broadcast operation
        logger.info(f"Broadcast summary for {conversation_id}: {success_count} success, {len(disconnected)} failed")
        
        # Clean up any disconnected clients
        for conn in disconnected:
            if conn in conversation_connections[conversation_id]:
                conversation_connections[conversation_id].remove(conn)
        
        if not conversation_connections[conversation_id]:
            logger.info(f"Removing empty conversation {conversation_id} from active connections")
            del conversation_connections[conversation_id]
    else:
        logger.warning(f"No active connections for conversation {conversation_id}")

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
    client_host = websocket.scope.get('client')[0] if websocket.scope.get('client') else "unknown"
    connection_id = f"{client_host}_{int(time.time())}"
    
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for conversation {conversation_id} from {client_host} (conn_id: {connection_id})")
    
    # Add this connection to active conversation connections with metadata
    if conversation_id not in conversation_connections:
        logger.info(f"Creating new conversation record for {conversation_id}")
        conversation_connections[conversation_id] = []
    
    conn_info = {
        "connection": websocket,
        "client_host": client_host,
        "connection_id": connection_id,
        "connected_at": time.time()
    }
    conversation_connections[conversation_id].append(conn_info)
    
    logger.info(f"Active connections for conversation {conversation_id}: {len(conversation_connections[conversation_id])}")
    
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
                elif message.get('type') == 'clear_conversation':
                    logger.info(f"Client requested to clear conversation {conversation_id}")
                    # You can add logic here to clear server-side conversation state
            except Exception as e:
                # If not valid JSON or other error, just log it
                logger.warning(f"Error processing websocket message: {str(e)}")
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for conversation {conversation_id} (conn_id: {connection_id})")
        
        # Remove this specific connection
        if conversation_id in conversation_connections:
            conversation_connections[conversation_id] = [
                conn for conn in conversation_connections[conversation_id] 
                if conn.get("connection_id") != connection_id
            ]
            
            logger.info(f"Remaining connections for conversation {conversation_id}: {len(conversation_connections[conversation_id])}")
            
            # If no more connections, remove the conversation record
            if not conversation_connections[conversation_id]:
                logger.info(f"No more connections for conversation {conversation_id}, removing record")
                del conversation_connections[conversation_id]
    except Exception as e:
        logger.error(f"An error occurred for conversation {conversation_id}: {e}")
        
        # Still try to clean up the connection
        if conversation_id in conversation_connections:
            conversation_connections[conversation_id] = [
                conn for conn in conversation_connections[conversation_id] 
                if conn.get("connection_id") != connection_id
            ]

# Add a new endpoint to clear session data
@router.get("/clear-session")
async def clear_session(request: Request):
    """Clear the session data for the current user"""
    try:
        # Clear session data
        request.session.clear()
        logger.info(f"Session cleared for client {request.client.host if request.client else 'unknown'}")
        return {"status": "success", "message": "Session cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing session: {str(e)}")
        return {"status": "error", "message": f"Failed to clear session: {str(e)}"}
