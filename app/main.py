"""Ingen aning: server. En process, allt speltillstånd i minnet."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .game import GameError, Room, new_code

STATIC = Path(__file__).parent.parent / "static"
ROOM_TTL = 6 * 3600

app = FastAPI(title="Ingen aning", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

rooms: dict[str, Room] = {}
# kod -> lista av (websocket, spelar-id eller None för TV)
conns: dict[str, list[tuple[WebSocket, str | None]]] = {}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/tv")
async def tv() -> FileResponse:
    return FileResponse(STATIC / "tv.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "rooms": len(rooms)}


def _sweep() -> None:
    now = time.time()
    for code in [c for c, r in rooms.items() if now - r.last_active > ROOM_TTL and not conns.get(c)]:
        rooms.pop(code, None)
        conns.pop(code, None)


async def _broadcast(room: Room) -> None:
    room.last_active = time.time()
    for ws, pid in list(conns.get(room.code, [])):
        view = room.view_tv() if pid is None else room.view_for(pid)
        try:
            await ws.send_json({"t": "state", "state": view})
        except Exception:
            pass  # stängs och städas av sin egen mottagarloop


def _act(room: Room, pid: str, msg: dict) -> None:
    t = msg.get("t")
    if t == "start":
        room.start_round(pid)
    elif t == "seen":
        room.mark_seen(pid)
    elif t == "openVote":
        room.open_vote(pid)
    elif t == "vote":
        room.vote(pid, str(msg.get("target", "")))
    elif t == "guess":
        room.guess(pid, str(msg.get("text", "")))
    elif t == "jury":
        room.jury_vote(pid, bool(msg.get("ok")))
    elif t == "force":
        room.force_close(pid)
    elif t == "lobby":
        room.to_lobby(pid)
    elif t == "category":
        room.set_category(pid, str(msg.get("id", "")))
    elif t == "kick":
        room.kick(pid, str(msg.get("pid", "")))
    elif t == "claimHost":
        room.claim_host(pid)
    else:
        raise GameError("Okänt kommando.")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    room: Room | None = None
    pid: str | None = None
    entry: tuple[WebSocket, str | None] | None = None
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            t = msg.get("t")
            if t == "ping":
                continue
            try:
                if entry is None:
                    code = str(msg.get("code", "")).upper().strip()
                    if t == "create":
                        _sweep()
                        room = Room(new_code(rooms))
                        rooms[room.code] = room
                        pid = room.add_player(str(msg.get("name", ""))).id
                    elif t == "join":
                        room = rooms.get(code)
                        if not room:
                            raise GameError("Hittar inget rum med den koden.")
                        old = str(msg.get("pid", ""))
                        if old and old in room.players:
                            pid = old
                        else:
                            pid = room.add_player(str(msg.get("name", ""))).id
                    elif t == "tv":
                        room = rooms.get(code)
                        if not room:
                            raise GameError("Hittar inget rum med den koden.")
                        pid = None
                    else:
                        raise GameError("Gå med i ett rum först.")
                    entry = (ws, pid)
                    conns.setdefault(room.code, []).append(entry)
                    if pid:
                        room.set_connected(pid, True)
                    await ws.send_json({"t": "joined", "code": room.code, "pid": pid})
                elif pid is None:
                    continue  # TV:n bara tittar
                else:
                    assert room
                    if pid not in room.players:
                        raise GameError("Du är inte längre med i rummet.")
                    _act(room, pid, msg)
            except GameError as err:
                await ws.send_json({"t": "error", "msg": str(err), "fatal": entry is None})
                continue
            assert room
            await _broadcast(room)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if room and entry:
            lst = conns.get(room.code, [])
            if entry in lst:
                lst.remove(entry)
            if pid and not any(p == pid for _, p in lst):
                room.set_connected(pid, False)
                await _broadcast(room)
