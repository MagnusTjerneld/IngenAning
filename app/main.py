"""Ingen aning: server. En process, allt speltillstånd i minnet."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .game import GameError, Room, new_code

STATIC = Path(__file__).parent.parent / "static"
ROOM_TTL = 6 * 3600
STALE_AFTER = 20.0   # sekunder utan livstecken innan en anslutning räknas som död
REAP_EVERY = 5.0


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    pid: str | None          # None för TV
    last: float = field(default_factory=time.monotonic)

    @property
    def alive(self) -> bool:
        return time.monotonic() - self.last < STALE_AFTER


rooms: dict[str, Room] = {}
conns: dict[str, list[Conn]] = {}


async def _reaper() -> None:
    """Stänger anslutningar som tystnat, t.ex. en mobil som somnat utan att säga hej då."""
    while True:
        await asyncio.sleep(REAP_EVERY)
        for lst in list(conns.values()):
            for c in list(lst):
                if not c.alive:
                    with suppress(Exception):
                        await c.ws.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_reaper())
    yield
    task.cancel()


app = FastAPI(title="Ingen aning", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
    for c in list(conns.get(room.code, [])):
        view = room.view_tv() if c.pid is None else room.view_for(c.pid)
        with suppress(Exception):  # en trasig anslutning städas av sin egen mottagarloop
            await c.ws.send_json({"t": "state", "state": view})


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


async def _join(room: Room, msg: dict) -> str:
    """Hittar spelarens plats i rummet. Samma person ska alltid hamna på samma plats igen."""
    old = str(msg.get("pid", ""))
    if old and old in room.players:
        return old
    name = str(msg.get("name", ""))
    same = room.find_by_name(name)
    if not same:
        return room.add_player(name).id
    mine = [c for c in conns.get(room.code, []) if c.pid == same.id]
    if any(c.alive for c in mine):
        raise GameError(f"Det finns redan en {same.name} i rummet. Välj ett annat namn.")
    # Samma namn och ingen levande anslutning: det är samma person som kommer tillbaka,
    # till exempel från en annan webbläsare. Hen tar över sin plats, mitt i rundan om det behövs.
    for c in mine:
        with suppress(Exception):
            await c.ws.close()
    return same.id


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    room: Room | None = None
    conn: Conn | None = None
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            if conn:
                conn.last = time.monotonic()
            t = msg.get("t")
            if t == "ping":
                await ws.send_json({"t": "pong"})
                continue
            try:
                if conn is None:
                    code = str(msg.get("code", "")).upper().strip()
                    if t == "create":
                        _sweep()
                        room = Room(new_code(rooms))
                        rooms[room.code] = room
                        pid = room.add_player(str(msg.get("name", ""))).id
                    elif t in ("join", "tv"):
                        room = rooms.get(code)
                        if not room:
                            raise GameError("Hittar inget rum med den koden.")
                        pid = await _join(room, msg) if t == "join" else None
                    else:
                        raise GameError("Gå med i ett rum först.")
                    conn = Conn(ws, pid)
                    conns.setdefault(room.code, []).append(conn)
                    if pid:
                        room.set_connected(pid, True)
                    await ws.send_json({"t": "joined", "code": room.code, "pid": pid})
                elif conn.pid is None:
                    continue  # TV:n bara tittar
                else:
                    assert room
                    if conn.pid not in room.players:
                        raise GameError("Du är inte längre med i rummet.")
                    _act(room, conn.pid, msg)
            except GameError as err:
                await ws.send_json({"t": "error", "msg": str(err), "fatal": conn is None})
                continue
            assert room
            await _broadcast(room)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if room and conn:
            lst = conns.get(room.code, [])
            if conn in lst:
                lst.remove(conn)
            if conn.pid and not any(c.pid == conn.pid for c in lst):
                room.set_connected(conn.pid, False)
                await _broadcast(room)
