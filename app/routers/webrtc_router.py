# import logging
# from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
# from typing import Dict, List
# import json

# router = APIRouter()

# # Set up logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # Store active connections


# class ConnectionManager:
#     def __init__(self):
#         self.active_connections: Dict[str, WebSocket] = {}
#         self.rooms: Dict[str, List[str]] = {}

#     async def connect(self, websocket: WebSocket, client_id: str):
#         await websocket.accept()
#         self.active_connections[client_id] = websocket
#         logger.info(f"Client {client_id} connected")

#     def disconnect(self, client_id: str):
#         if client_id in self.active_connections:
#             del self.active_connections[client_id]
#             logger.info(f"Client {client_id} disconnected")
#         for room in self.rooms.values():
#             if client_id in room:
#                 room.remove(client_id)

#     async def send_personal_message(self, message: str, client_id: str):
#         if client_id in self.active_connections:
#             await self.active_connections[client_id].send_text(message)

#     async def broadcast(self, message: str, exclude: str = None):
#         for client_id, connection in self.active_connections.items():
#             if client_id != exclude:
#                 await connection.send_text(message)

#     def create_room(self, room_id: str, client_id: str):
#         if room_id not in self.rooms:
#             self.rooms[room_id] = [client_id]
#         else:
#             self.rooms[room_id].append(client_id)
#         logger.info(f"Client {client_id} joined room {room_id}")

#     def get_room_members(self, room_id: str) -> List[str]:
#         return self.rooms.get(room_id, [])


# manager = ConnectionManager()


# @router.websocket("/ws/{client_id}")
# async def websocket_endpoint(websocket: WebSocket, client_id: str):
#     await manager.connect(websocket, client_id)
#     try:
#         while True:
#             data = await websocket.receive_text()
#             try:
#                 message = json.loads(data)
#                 if message['type'] == 'offer':
#                     await handle_offer(client_id, message)
#                 elif message['type'] == 'answer':
#                     await handle_answer(client_id, message)
#                 elif message['type'] == 'ice-candidate':
#                     await handle_ice_candidate(client_id, message)
#                 elif message['type'] == 'join-room':
#                     handle_join_room(client_id, message)
#                 else:
#                     logger.warning(
#                         f"Unknown message type from {client_id}: {message['type']}")
#             except json.JSONDecodeError:
#                 logger.error(f"Invalid JSON from client {client_id}")
#             except KeyError:
#                 logger.error(f"Invalid message format from client {client_id}")
#     except WebSocketDisconnect:
#         manager.disconnect(client_id)
#         await manager.broadcast(json.dumps({
#             "type": "user-disconnected",
#             "client_id": client_id
#         }))


# async def handle_offer(client_id: str, message: Dict):
#     if 'to' in message and message['to'] in manager.active_connections:
#         await manager.send_personal_message(json.dumps({
#             "type": "offer",
#             "offer": message['offer'],
#             "from": client_id
#         }), message['to'])
#     else:
#         logger.warning(f"Invalid 'to' field in offer from {client_id}")


# async def handle_answer(client_id: str, message: Dict):
#     if 'to' in message and message['to'] in manager.active_connections:
#         await manager.send_personal_message(json.dumps({
#             "type": "answer",
#             "answer": message['answer'],
#             "from": client_id
#         }), message['to'])
#     else:
#         logger.warning(f"Invalid 'to' field in answer from {client_id}")


# async def handle_ice_candidate(client_id: str, message: Dict):
#     if 'to' in message and message['to'] in manager.active_connections:
#         await manager.send_personal_message(json.dumps({
#             "type": "ice-candidate",
#             "candidate": message['candidate'],
#             "from": client_id
#         }), message['to'])
#     else:
#         logger.warning(f"Invalid 'to' field in ICE candidate from {client_id}")


# def handle_join_room(client_id: str, message: Dict):
#     if 'room' in message:
#         room_id = message['room']
#         manager.create_room(room_id, client_id)
#         members = manager.get_room_members(room_id)
#         for member in members:
#             if member != client_id:
#                 manager.send_personal_message(json.dumps({
#                     "type": "new-user-joined",
#                     "client_id": client_id,
#                     "room": room_id
#                 }), member)
#     else:
#         logger.warning(
#             f"Invalid 'room' field in join-room message from {client_id}")


# @router.get("/get-online-users")
# async def get_online_users():
#     return {"online_users": list(manager.active_connections.keys())}


# @router.get("/get-room-members/{room_id}")
# async def get_room_members(room_id: str):
#     members = manager.get_room_members(room_id)
#     if members:
#         return {"room_members": members}
#     else:
#         raise HTTPException(status_code=404, detail="Room not found")
