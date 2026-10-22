"""Live dashboard WebSocket route. All pub/sub + metrics state lives in
dashboard/service.py; this module only wires the transport."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from support_portal.dashboard import service

router = APIRouter()


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    service.register_connection(websocket)
    await websocket.send_json({"type": "snapshot", "data": service.snapshot()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        service.unregister_connection(websocket)
