"""
Snowman Dance — Real-time Couple's Rhythm Game Server
FastAPI + WebSockets backend

Features:
- Role Selection: Boy (Left) & Girl (Right)
- Complementary dance-step matching system:
    * Reach Out (Boy) + Take Hand (Girl)
    * Spin Her (Boy) + Twirl (Girl)
    * Dip (Boy) + Lean Back (Girl)
- Server as strict source of truth for 5-second rounds
- Real-time dance step animations triggered only on click/sync
- Round success (+20% vibe, sprite row animation) & fail (-10% vibe, stumble)
- Winning state (100% vibe) -> slide to center -> letter screen
"""

import os
import asyncio
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("snowman_server")

app = FastAPI(title="Snowman Dance Game")

# ── Static assets ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(TEMPLATE_DIR / "index.html")


# Persistent store for room letters so they are never lost on disconnect/reload
GLOBAL_ROOM_LETTERS: Dict[str, List[dict]] = {}


def deduplicate_letters_list(letters: List[dict]) -> List[dict]:
    """Ensure no duplicates exist in letter collections by sender+body+approximate time."""
    deduped = []
    for l in letters:
        body = str(l.get("body", l.get("text", ""))).strip()
        sender = str(l.get("sender", "")).strip().lower()
        ts = float(l.get("timestamp", 0))
        is_dup = False
        for ex in deduped:
            if l.get("id") and ex.get("id") and l["id"] == ex["id"]:
                is_dup = True
                break
            ex_body = str(ex.get("body", ex.get("text", ""))).strip()
            ex_sender = str(ex.get("sender", "")).strip().lower()
            ex_ts = float(ex.get("timestamp", 0))
            if ex_body == body and ex_sender == sender:
                if ts > 0 and ex_ts > 0 and abs(ts - ex_ts) < 8.0:
                    is_dup = True
                    break
                elif l.get("time") and ex.get("time") and l["time"] == ex["time"]:
                    is_dup = True
                    break
        if not is_dup:
            deduped.append(l)
    return deduped


def find_recent_duplicate_letter(room, sender_id: str, sender_name: str, body_text: str, window_seconds: float = 6.0) -> Optional[dict]:
    now = time.time()
    clean_body = body_text.strip()
    clean_sender = sender_name.strip().lower()
    for letter in reversed(room.letters[-10:]):
        ts = letter.get("timestamp", 0)
        if (now - ts) <= window_seconds:
            existing_body = str(letter.get("body", letter.get("text", ""))).strip()
            existing_sender = str(letter.get("sender", "")).strip().lower()
            existing_sender_id = str(letter.get("sender_id", ""))

            same_sender = (
                (sender_id and existing_sender_id and sender_id == existing_sender_id) or
                (clean_sender and existing_sender and clean_sender == existing_sender) or
                (sender_id and sender_id == existing_sender_id)
            )
            if existing_body == clean_body and same_sender:
                return letter
    return None


@app.get("/api/room/{room_id}/letters")
async def get_room_letters(room_id: str):
    """Fetch stored letters for a room so clients can check notifications on page open and poll in real time."""
    letters = GLOBAL_ROOM_LETTERS.get(room_id)
    if letters is None:
        room = rooms.get(room_id)
        letters = room.letters if room else []
    return {"room_code": room_id, "letters": deduplicate_letters_list(letters)}


@app.post("/api/room/{room_id}/letter")
async def post_room_letter(room_id: str, payload: dict):
    """Allow sending a note via HTTP (e.g. from lobby mailbox) even before WS join."""
    room = get_or_create_room(room_id)
    recipient = payload.get("recipient", "")[:50]
    body_text = payload.get("body", payload.get("text", ""))[:4000]
    sender_name = payload.get("sender", "Partner")[:50]
    sender_id = payload.get("sender_id", "")

    # Check for recent duplicate to prevent double-receive glitch
    dup = find_recent_duplicate_letter(room, sender_id, sender_name, body_text)
    if dup:
        logger.info(f"Room '{room_id}': Ignored duplicate HTTP letter from {sender_name}")
        return {"status": "ok", "letter": dup, "duplicate": True}

    time_str = time.strftime("%I:%M %p")
    letter_obj = {
        "id": len(room.letters) + 1,
        "recipient": recipient,
        "body": body_text,
        "text": body_text,
        "sender": sender_name,
        "sender_id": sender_id,
        "time": time_str,
        "timestamp": time.time()
    }
    room.letters.append(letter_obj)
    room.letters = deduplicate_letters_list(room.letters)
    GLOBAL_ROOM_LETTERS[room_id] = room.letters

    # Broadcast to all other connected WebSocket clients in this room!
    for pid, ws_conn in list(room.connections.items()):
        if pid != sender_id:
            await room.send_to(pid, {
                "type": "letter_received",
                **letter_obj
            })
    return {"status": "ok", "letter": letter_obj}


# ── Complementary Move Pairs ───────────────────────────────────────────────────

COMPLEMENTARY_PAIRS = {
    ("reach_out", "take_hand"): {
        "index": 1,
        "name": "Reach Out + Take Hand",
        "description": "Their hands meet in winter warmth ✨"
    },
    ("spin_her", "twirl"): {
        "index": 2,
        "name": "Spin Her + Twirl",
        "description": "A graceful snowy twirl 💫"
    },
    ("dip", "lean_back"): {
        "index": 3,
        "name": "Dip + Lean Back",
        "description": "A breathtaking romantic dip 💕"
    }
}


# ── Room State & Management ────────────────────────────────────────────────────

class Room:
    """
    Tracks room connections, roles (boy/girl), and coordinates 5-second round evaluation.
    """

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.connections: Dict[str, WebSocket] = {}   # player_id -> WebSocket
        self.names: Dict[str, str] = {}               # player_id -> display name
        self.roles: Dict[str, str] = {}               # player_id -> "boy" | "girl"
        self.round_moves: Dict[str, str] = {}         # player_id -> chosen move
        self.vibe: int = 0                            # 0 to 100
        self.game_active: bool = False
        self.game_won: bool = False
        self.round_number: int = 0
        self.round_duration: float = 10.0             # 10-second synchronized window
        self.round_start_time: float = 0.0
        self.round_resolved: bool = False
        self.round_task: Optional[asyncio.Task] = None
        self.letters: List[dict] = []

    @property
    def player_count(self) -> int:
        return len(self.connections)

    @property
    def full(self) -> bool:
        return self.player_count >= 2

    @property
    def has_opposite_roles(self) -> bool:
        """Returns True if exactly one Boy and one Girl are registered."""
        role_vals = list(self.roles.values())
        return len(role_vals) == 2 and "boy" in role_vals and "girl" in role_vals

    def other_player(self, player_id: str) -> Optional[str]:
        for pid in self.connections:
            if pid != player_id:
                return pid
        return None

    def get_boy_player(self) -> Optional[str]:
        for pid, r in self.roles.items():
            if r == "boy":
                return pid
        return None

    def get_girl_player(self) -> Optional[str]:
        for pid, r in self.roles.items():
            if r == "girl":
                return pid
        return None

    async def broadcast(self, message: dict, exclude: Optional[str] = None):
        """Broadcast message to all connected players in this room."""
        payload = json.dumps(message)
        dead = []
        for pid, ws in list(self.connections.items()):
            if pid == exclude:
                continue
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to {pid} in room {self.room_id}: {e}")
                dead.append(pid)
        for pid in dead:
            self.connections.pop(pid, None)

    async def send_to(self, player_id: str, message: dict):
        """Send message to a specific player in this room."""
        ws = self.connections.get(player_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"Failed to send direct message to {player_id}: {e}")

    async def start_round(self):
        """
        SERVER SOURCE OF TRUTH:
        Emits 'start_round' with 5.0s timer to both players.
        """
        if not self.full or self.game_won or not self.has_opposite_roles:
            return

        # Cancel any previous round task
        if self.round_task and not self.round_task.done():
            self.round_task.cancel()

        self.round_number += 1
        self.round_resolved = False
        self.round_moves.clear()
        self.round_start_time = time.time()
        self.game_active = True
        current_round = self.round_number

        logger.info(
            f"ROOM '{self.room_id}': Emitting 'start_round' #{current_round} "
            f"(duration: {self.round_duration}s) to {len(self.connections)} players."
        )

        # Broadcast 'start_round' event explicitly to the room
        await emit_to_room(self.room_id, {
            "type": "start_round",
            "event": "start_round",
            "room_code": self.room_id,
            "round": current_round,
            "duration": self.round_duration,
            "server_time": self.round_start_time,
            "names": self.names,
            "roles": self.roles,
            "boy_player": self.get_boy_player(),
            "girl_player": self.get_girl_player(),
            "vibe": self.vibe
        })

        # Run 5.0-second timer on server to evaluate choices
        self.round_task = asyncio.create_task(
            self._round_evaluation_tracker(current_round)
        )

    async def _round_evaluation_tracker(self, round_id: int):
        """
        Runs the 10-second round window, then strictly evaluates the move choices if not already resolved.
        """
        try:
            # Wait for up to 10.0 seconds
            await asyncio.sleep(self.round_duration)
            await self.evaluate_round(round_id)
        except asyncio.CancelledError:
            pass

    async def evaluate_round(self, round_id: int):
        """
        Strictly evaluates choices for the round — either after 10s expiration
        OR immediately as soon as both players click their moves!
        """
        if (
            self.round_number != round_id
            or self.round_resolved
            or self.game_won
            or not self.game_active
        ):
            return

        self.round_resolved = True
        logger.info(f"ROOM '{self.room_id}': Evaluating Round #{round_id}...")

        boy_pid = self.get_boy_player()
        girl_pid = self.get_girl_player()

        boy_move = self.round_moves.get(boy_pid) if boy_pid else None
        girl_move = self.round_moves.get(girl_pid) if girl_pid else None

        logger.info(f"ROOM '{self.room_id}' Round #{round_id}: Boy move='{boy_move}', Girl move='{girl_move}'")

        pair_info = COMPLEMENTARY_PAIRS.get((boy_move, girl_move))

        if pair_info is not None:
            # ── SUCCESS: Complementary pair match ────────────────────────
            self.vibe = min(100, self.vibe + 20)
            logger.info(
                f"ROOM '{self.room_id}': ROUND SUCCESS! Pair: {pair_info['name']} -> New Vibe: {self.vibe}%"
            )

            await emit_to_room(self.room_id, {
                "type": "round_success",
                "event": "round_success",
                "room_code": self.room_id,
                "round": round_id,
                "boy_move": boy_move,
                "girl_move": girl_move,
                "pair_index": pair_info["index"],
                "pair_name": pair_info["name"],
                "description": pair_info["description"],
                "vibe": self.vibe
            })

            if self.vibe >= 100:
                self.game_won = True
                self.game_active = False
                logger.info(f"ROOM '{self.room_id}': GAME WON! Reached 100% Vibe.")
                await emit_to_room(self.room_id, {
                    "type": "game_win",
                    "event": "game_win",
                    "room_code": self.room_id,
                    "vibe": 100
                })
            else:
                # Wait 2.6s for dance sprite animation and celebration, then start next round
                await asyncio.sleep(2.6)
                if self.game_active and not self.game_won and self.full:
                    await self.start_round()

        else:
            # ── FAILURE: Mismatch or missed move ─────────────────────────
            self.vibe = max(0, self.vibe - 10)

            # Form descriptive feedback message
            if not boy_move and not girl_move:
                reason = "Neither player chose a move in time! ❄️"
            elif not boy_move:
                reason = "Boy didn't choose a move in time! ❄️"
            elif not girl_move:
                reason = "Girl didn't choose a move in time! ❄️"
            else:
                b_label = boy_move.replace("_", " ").title()
                g_label = girl_move.replace("_", " ").title()
                reason = f"Mismatch: {b_label} + {g_label}! Steps stumbled… ❄️"

            logger.info(f"ROOM '{self.room_id}': ROUND FAIL! {reason} -> New Vibe: {self.vibe}%")

            await emit_to_room(self.room_id, {
                "type": "round_fail",
                "event": "round_fail",
                "room_code": self.room_id,
                "round": round_id,
                "boy_move": boy_move,
                "girl_move": girl_move,
                "reason": reason,
                "vibe": self.vibe
            })

            # Wait 2.2s for stumble animation, then start next round
            await asyncio.sleep(2.2)
            if self.game_active and not self.game_won and self.full:
                await self.start_round()


# Global room registry
rooms: Dict[str, Room] = {}


def get_or_create_room(room_id: str) -> Room:
    if room_id not in rooms:
        rooms[room_id] = Room(room_id)
        if room_id in GLOBAL_ROOM_LETTERS:
            rooms[room_id].letters = GLOBAL_ROOM_LETTERS[room_id]
        else:
            GLOBAL_ROOM_LETTERS[room_id] = rooms[room_id].letters
    return rooms[room_id]


async def emit_to_room(room_code: str, event_data: dict, exclude: Optional[str] = None):
    """
    Explicitly broadcasts an event to all connected clients in the specified room.
    """
    room = rooms.get(room_code)
    if not room:
        logger.warning(f"emit_to_room: room '{room_code}' not found")
        return
    if "room_code" not in event_data:
        event_data["room_code"] = room_code
    if "type" in event_data and "event" not in event_data:
        event_data["event"] = event_data["type"]
    await room.broadcast(event_data, exclude=exclude)


# ── WebSocket Endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws/{room_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, player_id: str):
    await websocket.accept()

    room = get_or_create_room(room_id)

    # Clean up any dead or disconnected sockets
    dead = [pid for pid, conn in list(room.connections.items()) if conn.client_state.name == "DISCONNECTED"]
    for pid in dead:
        room.connections.pop(pid, None)

    # If this player is reconnecting with an existing open socket, safely close the old one
    if player_id in room.connections:
        old_conn = room.connections.get(player_id)
        if old_conn and old_conn != websocket:
            try:
                await old_conn.close()
            except Exception:
                pass

    # Reject only if room already has 2 different active connected players
    if room.full and player_id not in room.connections:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Room is full! Please choose or create a different room code."
        }))
        await websocket.close()
        return

    room.connections[player_id] = websocket
    logger.info(f"Player {player_id} connected to room '{room_id}'. Total: {room.player_count}")

    # Confirm connection to player
    await room.send_to(player_id, {
        "type": "connected",
        "player_id": player_id,
        "room_code": room_id,
        "player_count": room.player_count,
        "letters": room.letters
    })

    # Notify partner if present
    other = room.other_player(player_id)
    if other:
        await room.send_to(other, {
            "type": "partner_connected",
            "partner_id": player_id,
            "partner_name": room.names.get(player_id, "Partner"),
            "partner_role": room.roles.get(player_id, "")
        })

    try:
        async for raw in websocket.iter_text():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            # ── REGISTER NAME & ROLE ────────────────────────────────────────
            if msg_type == "register":
                name = data.get("name", player_id).strip()[:20] or "Dancer"
                role = data.get("role", "boy").lower().strip()
                if role not in ("boy", "girl"):
                    role = "boy"

                room.names[player_id] = name
                room.roles[player_id] = role
                logger.info(f"Player {player_id} registered as '{name}' with role '{role}' in room '{room_id}'")

                await room.send_to(player_id, {
                    "type": "registered",
                    "player_id": player_id,
                    "name": name,
                    "role": role
                })

                other = room.other_player(player_id)
                if other:
                    await room.send_to(other, {
                        "type": "partner_info",
                        "partner_id": player_id,
                        "partner_name": name,
                        "partner_role": role
                    })

                # Check roles when room is full (2 players)
                if room.full:
                    other_role = room.roles.get(other)
                    if other_role and other_role == role:
                        # Conflict! Both picked the same role
                        conflict_msg = (
                            f"Both players chose {role.capitalize()}! "
                            f"One player must play as Boy and one as Girl."
                        )
                        logger.warning(f"Room '{room_id}': Role conflict! Both are '{role}'")
                        await room.send_to(player_id, {
                            "type": "role_conflict",
                            "message": conflict_msg,
                            "partner_role": other_role
                        })
                    elif room.has_opposite_roles and not room.game_active:
                        # STRICT RULE: Opposite roles picked! Server begins round 1.
                        room.game_active = True
                        room.vibe = 0
                        room.game_won = False
                        logger.info(f"Room '{room_id}': Boy and Girl ready! Starting round 1...")

                        await emit_to_room(room_id, {
                            "type": "both_ready",
                            "names": room.names,
                            "roles": room.roles,
                            "boy_player": room.get_boy_player(),
                            "girl_player": room.get_girl_player()
                        })

                        await asyncio.sleep(0.4)
                        await room.start_round()

            # ── DANCE MOVE SELECTION ────────────────────────────────────────
            elif msg_type == "dance_move":
                move = data.get("move", "")
                round_num = data.get("round", room.round_number)

                if round_num == room.round_number and not room.round_resolved:
                    room.round_moves[player_id] = move
                    player_role = room.roles.get(player_id, "")
                    logger.info(
                        f"Room '{room_id}': Player {player_id} ({player_role}) "
                        f"chose move '{move}' for round {round_num}"
                    )

                    # Acknowledge move locked to player
                    await room.send_to(player_id, {
                        "type": "move_locked",
                        "move": move,
                        "round": round_num
                    })

                    # Notify partner with the move so partner's character animates
                    other = room.other_player(player_id)
                    if other:
                        await room.send_to(other, {
                            "type": "partner_moved",
                            "partner_id": player_id,
                            "partner_role": player_role,
                            "move": move
                        })

                    # Check if BOTH players have chosen their moves:
                    boy_pid = room.get_boy_player()
                    girl_pid = room.get_girl_player()
                    if boy_pid in room.round_moves and girl_pid in room.round_moves:
                        logger.info(
                            f"Room '{room_id}' Round #{round_num}: Both players clicked their moves! "
                            f"Evaluating immediately without waiting for timer!"
                        )
                        if room.round_task and not room.round_task.done():
                            room.round_task.cancel()
                        room.round_task = asyncio.create_task(
                            room.evaluate_round(round_num)
                        )

            # ── SHARE NOTE / LETTER ─────────────────────────────────────────
            elif msg_type == "share_letter":
                recipient = data.get("recipient", "")[:50]
                body_text = data.get("body", data.get("text", ""))[:4000]
                sender_name = data.get("sender", room.names.get(player_id, "Someone"))[:50]

                # Check for recent duplicate to prevent double-receive glitch
                dup = find_recent_duplicate_letter(room, player_id, sender_name, body_text)
                if dup:
                    logger.info(f"Room '{room_id}': Ignored duplicate WS letter from {sender_name}")
                    await room.send_to(player_id, {
                        "type": "letter_sent_confirm",
                        **dup
                    })
                    continue

                time_str = time.strftime("%I:%M %p")
                letter_obj = {
                    "id": len(room.letters) + 1,
                    "recipient": recipient,
                    "body": body_text,
                    "text": body_text,
                    "sender": sender_name,
                    "sender_id": player_id,
                    "time": time_str,
                    "timestamp": time.time()
                }
                room.letters.append(letter_obj)
                room.letters = deduplicate_letters_list(room.letters)
                GLOBAL_ROOM_LETTERS[room_id] = room.letters

                # Broadcast to all other connected players in this room!
                for pid in list(room.connections.keys()):
                    if pid != player_id:
                        await room.send_to(pid, {
                            "type": "letter_received",
                            **letter_obj
                        })
                await room.send_to(player_id, {
                    "type": "letter_sent_confirm",
                    **letter_obj
                })

            # ── PLAY AGAIN / RESTART DANCE ──────────────────────────────────
            elif msg_type == "play_again":
                logger.info(f"Room '{room_id}': Player {player_id} requested Play Again!")
                if room.round_task and not room.round_task.done():
                    room.round_task.cancel()

                room.vibe = 0
                room.round_number = 0
                room.round_moves.clear()
                room.round_resolved = False
                room.game_won = False
                room.game_active = True

                await emit_to_room(room_id, {
                    "type": "game_reset",
                    "room_code": room_id,
                    "reset_by": player_id,
                    "reset_by_name": room.names.get(player_id, "Partner")
                })

                await asyncio.sleep(0.8)
                if room.game_active and room.full and room.has_opposite_roles:
                    await room.start_round()

    except WebSocketDisconnect:
        logger.info(f"Player {player_id} disconnected from room '{room_id}'")
    finally:
        room.connections.pop(player_id, None)
        room.names.pop(player_id, None)
        room.roles.pop(player_id, None)
        room.round_moves.pop(player_id, None)

        if room.round_task and not room.round_task.done():
            room.round_task.cancel()

        room.game_active = False

        other = room.other_player(player_id)
        if other:
            await room.send_to(other, {
                "type": "partner_disconnected",
                "partner_id": player_id
            })

        # Clean up empty rooms but preserve letters
        if not room.connections:
            GLOBAL_ROOM_LETTERS[room_id] = room.letters
            rooms.pop(room_id, None)
            logger.info(f"Room '{room_id}' closed connections, letters preserved.")


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )
