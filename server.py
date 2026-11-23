#!/usr/bin/env python3
"""
Spelling Bee Server
A local network spelling competition for classrooms
No authentication, no ads
Requires: websockets  (pip install websockets)
Uses: http.server + threading for static files

Avatars powered by DiceBear API (https://api.dicebear.com)
"""
import asyncio
import websockets
import json
import random
import string
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import os
import time
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Default Word list (word, definition)
# ---------------------------------------------------------------------------
DEFAULT_WORD_LIST = []

DICEBEAR_STYLES = [
    "avataaars", "bottts", "lorelei", "notionists",
    "adventurer", "big-smile", "fun-emoji", "thumbs",
    "identicon", "shapes"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STUDENT_TXT_PATH = os.path.join(BASE_DIR, "student.txt")

games = {}          # game_code -> Game
connections = {}    # client_id -> websocket


def sync_student_txt():
    """Keep student.txt automatically synced with currently connected students."""
    try:
        lines = []
        for code, game in games.items():
            for pid, p in game.players.items():
                lines.append(f"{code} | {pid} | {p['name']} | score={p['score']}")
        with open(STUDENT_TXT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
    except Exception as e:
        print(f"Failed to sync student.txt: {e}")


def make_avatar_url(style: str, seed: str) -> str:
    style = style if style in DICEBEAR_STYLES else "avataaars"
    seed = quote(seed or "player")
    return f"https://api.dicebear.com/9.x/{style}/svg?seed={seed}&size=128"


def normalize_code(raw) -> str:
    return str(raw or "").strip().upper()


def normalize_pid(raw) -> str:
    return str(raw or "").strip()


class Game:
    def __init__(self, game_id, teacher_websocket=None):
        self.game_id = game_id
        self.teacher_websocket = teacher_websocket
        self.players = {}
        self.num_rounds = 5
        self.timer_seconds = 20
        self.word_bank = list(DEFAULT_WORD_LIST)  # [(word, definition), ...]
        self.words = []                           # active match sample
        self.current_round = 0
        self.phase = "lobby"
        self.round_ends_at = 0
        self.last_results = {}
        self.ranking = []
        self._round_task = None
        self._stop_requested = False

        self.paused = False
        self.paused_remaining = 0.0
        self.advance_event = asyncio.Event()

    def add_player(self, player_name, websocket, avatar_style="avataaars", avatar_seed=None):
        player_id = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        seed = avatar_seed or player_name or player_id
        avatar_url = make_avatar_url(avatar_style, seed)

        self.players[player_id] = {
            "name": player_name,
            "websocket": websocket,
            "score": 0,
            "answered": False,
            "last_answer": None,
            "live_input": "",
            "avatar": avatar_url,
            "avatar_style": avatar_style,
            "avatar_seed": seed,
        }
        sync_student_txt()
        return player_id

    def remove_player(self, player_id):
        player_id = normalize_pid(player_id)
        if not player_id or player_id not in self.players:
            return False, None, None

        p = self.players.pop(player_id)
        name = p.get("name", "???")
        ws = p.get("websocket")

        if player_id in self.last_results:
            del self.last_results[player_id]

        sync_student_txt()
        return True, name, ws

    def set_config(self, rounds, timer):
        if isinstance(rounds, int) and 1 <= rounds <= 50:
            self.num_rounds = rounds
        if isinstance(timer, int) and 5 <= timer <= 180:
            self.timer_seconds = timer

    def update_word_bank(self, entries, mode="replace"):
        cleaned = []
        seen = set()
        if mode == "append":
            for w, d in self.word_bank:
                lw = w.strip().lower()
                if lw and lw not in seen:
                    seen.add(lw)
                    cleaned.append((lw, d.strip()))

        for item in entries:
            if not isinstance(item, dict):
                continue
            w = str(item.get("word") or "").strip().lower()
            d = str(item.get("definition") or "").strip()
            if w and d and w not in seen:
                seen.add(w)
                cleaned.append((w, d))

        if cleaned:
            self.word_bank = cleaned
            if self.num_rounds > len(self.word_bank):
                self.num_rounds = len(self.word_bank)
        return len(self.word_bank)

    def prepare_words(self):
        pool = self.word_bank if self.word_bank else DEFAULT_WORD_LIST
        count = min(self.num_rounds, len(pool))
        self.words = random.sample(pool, count)
        self.num_rounds = len(self.words)

    def can_pause(self):
        return self.phase in ("countdown", "playing", "round_result") and not self.paused

    def pause(self):
        if not self.can_pause():
            return False
        if self.phase == "playing":
            self.paused_remaining = max(0.0, self.round_ends_at - time.time())
        self.paused = True
        return True

    def resume(self):
        if not self.paused:
            return False
        if self.phase == "playing":
            self.round_ends_at = time.time() + self.paused_remaining
        self.paused = False
        return True

    def time_left(self):
        if self.phase != "playing":
            return self.timer_seconds
        if self.paused:
            return max(0, int(round(self.paused_remaining)))
        return max(0, int(self.round_ends_at - time.time()))

    def get_state(self, for_teacher=False):
        players_public = {}
        for pid, p in self.players.items():
            player_info = {
                "name": p["name"],
                "score": p["score"],
                "answered": p.get("answered", False),
                "avatar": p.get("avatar"),
            }
            if for_teacher:
                player_info["live_input"] = p.get("live_input", "")
            players_public[pid] = player_info

        state = {
            "game_id": self.game_id,
            "phase": self.phase,
            "paused": self.paused,
            "num_rounds": self.num_rounds,
            "timer_seconds": self.timer_seconds,
            "current_round": self.current_round,
            "total_rounds": self.num_rounds,
            "players": players_public,
            "last_results": self.last_results,
            "ranking": self.ranking,
        }

        if self.phase in ("playing", "countdown", "round_result") and self.current_round > 0 and self.current_round <= len(self.words):
            word, definition = self.words[self.current_round - 1]
            state["time_left"] = self.time_left()
            state["definition"] = definition
            state["letter_count"] = len(word)
            state["first_letter"] = word[0].upper()
            if for_teacher:
                state["word"] = word
            if self.phase == "round_result":
                state["correct_word"] = word

        if self.phase == "game_over":
            state["ranking"] = self.ranking

        if for_teacher:
            active_source = self.words if self.words else self.word_bank
            state["word_list"] = [
                {"word": w, "definition": d} for w, d in active_source
            ]
            state["word_bank_count"] = len(self.word_bank)

        return state


def generate_game_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def send_json(ws, obj):
    try:
        await ws.send(json.dumps(obj))
    except Exception:
        pass


async def broadcast_game_state(game_code):
    if game_code not in games:
        return
    game = games[game_code]

    if game.teacher_websocket:
        await send_json(game.teacher_websocket, {
            "type": "game_state",
            "game_state": game.get_state(for_teacher=True),
        })

    for pid, p in list(game.players.items()):
        await send_json(p["websocket"], {
            "type": "game_state",
            "game_state": game.get_state(for_teacher=False),
            "player_id": pid,
        })


async def pausable_sleep(game, seconds):
    remaining = float(seconds)
    last = time.time()
    while remaining > 0:
        if game._stop_requested:
            return
        await asyncio.sleep(0.1)
        now = time.time()
        if not game.paused:
            remaining -= (now - last)
        last = now


async def run_rounds(game_code):
    game = games.get(game_code)
    if not game:
        return

    try:
        game._stop_requested = False
        game.prepare_words()
        game.phase = "countdown"
        await broadcast_game_state(game_code)
        await pausable_sleep(game, 3)

        for r in range(1, game.num_rounds + 1):
            game = games.get(game_code)
            if not game or game._stop_requested:
                return

            word, definition = game.words[r - 1]
            game.current_round = r
            game.phase = "playing"
            game.round_ends_at = time.time() + game.timer_seconds
            game.paused_remaining = float(game.timer_seconds)

            for p in game.players.values():
                p["answered"] = False
                p["last_answer"] = None
                p["live_input"] = ""

            print(f"[{game_code}] Round {r}/{game.num_rounds}: {word}")
            await broadcast_game_state(game_code)

            last_broadcast = 0
            while True:
                if game._stop_requested:
                    return
                await asyncio.sleep(0.25)

                if not game.paused:
                    if time.time() >= game.round_ends_at:
                        break
                    if game.players and all(p.get("answered") for p in game.players.values()):
                        break

                now = time.time()
                if now - last_broadcast >= 1.0:
                    await broadcast_game_state(game_code)
                    last_broadcast = now

            if game._stop_requested:
                return

            results = {}
            for pid, p in game.players.items():
                ans = (p.get("last_answer") or "").strip().lower()
                correct = ans == word.lower()
                if correct:
                    p["score"] += 1
                results[pid] = {
                    "name": p["name"],
                    "answer": p.get("last_answer") or "(no answer)",
                    "correct": correct,
                    "score": p["score"],
                    "avatar": p.get("avatar"),
                }
            sync_student_txt()
            game.last_results = results
            game.phase = "round_result"
            print(f"[{game_code}] Round {r} results: {results}")
            await broadcast_game_state(game_code)

            game.advance_event.clear()
            await game.advance_event.wait()
            if game._stop_requested:
                return

        game = games.get(game_code)
        if not game or game._stop_requested:
            return

        ranking = sorted(
            [
                {
                    "name": p["name"],
                    "score": p["score"],
                    "avatar": p.get("avatar"),
                }
                for p in game.players.values()
            ],
            key=lambda x: -x["score"],
        )
        game.ranking = ranking
        game.paused = False
        game.phase = "game_over"
        print(f"[{game_code}] GAME OVER: {ranking}")
        await broadcast_game_state(game_code)
    except asyncio.CancelledError:
        pass


async def handle_websocket(websocket):
    client_id = id(websocket)
    connections[client_id] = websocket

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            action = data.get("action")

            if action == "create_game":
                code = generate_game_code()
                while code in games:
                    code = generate_game_code()
                games[code] = Game(code, teacher_websocket=websocket)
                sync_student_txt()
                await send_json(websocket, {
                    "type": "game_created",
                    "game_code": code,
                    "game_state": games[code].get_state(for_teacher=True),
                })
                print(f"Game created: {code}")

            elif action == "set_config":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    if game.teacher_websocket is websocket and game.phase == "lobby":
                        game.set_config(data.get("rounds"), data.get("timer"))
                        await broadcast_game_state(code)

            elif action == "update_word_bank":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    if game.teacher_websocket is websocket:
                        mode = data.get("mode", "replace")
                        entries = data.get("words") or []
                        total = game.update_word_bank(entries, mode=mode)
                        await broadcast_game_state(code)
                        await send_json(websocket, {
                            "type": "word_bank_updated",
                            "mode": mode,
                            "total": total,
                        })

            elif action == "join_game":
                code = normalize_code(data.get("game_code"))
                name = (data.get("player_name") or "Anonymous").strip()[:20]
                avatar_style = data.get("avatar_style", "avataaars")
                avatar_seed = data.get("avatar_seed")

                if code not in games:
                    await send_json(websocket, {"type": "error", "message": "Game not found"})
                    continue
                game = games[code]
                if game.phase != "lobby":
                    await send_json(websocket, {"type": "error", "message": "Game already started"})
                    continue
                if any(p["name"].lower() == name.lower() for p in game.players.values()):
                    await send_json(websocket, {"type": "error", "message": "Name already taken"})
                    continue

                pid = game.add_player(name, websocket, avatar_style, avatar_seed)
                await send_json(websocket, {
                    "type": "joined",
                    "player_id": pid,
                    "game_state": game.get_state(for_teacher=False),
                })
                await broadcast_game_state(code)

            elif action == "start_game":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    if game.teacher_websocket is websocket and game.phase == "lobby":
                        if not game.players:
                            await send_json(websocket, {"type": "error", "message": "No players yet"})
                            continue
                        game.paused = False
                        game.phase = "countdown"
                        game._round_task = asyncio.create_task(run_rounds(code))

            elif action == "pause_game":
                code = normalize_code(data.get("game_code"))
                if code in games and games[code].teacher_websocket is websocket:
                    if games[code].pause():
                        await broadcast_game_state(code)

            elif action == "resume_game":
                code = normalize_code(data.get("game_code"))
                if code in games and games[code].teacher_websocket is websocket:
                    if games[code].resume():
                        await broadcast_game_state(code)

            elif action == "toggle_pause":
                code = normalize_code(data.get("game_code"))
                if code in games and games[code].teacher_websocket is websocket:
                    game = games[code]
                    changed = game.resume() if game.paused else game.pause()
                    if changed:
                        await broadcast_game_state(code)

            elif action == "next_round":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    if game.teacher_websocket is websocket and game.phase == "round_result":
                        game.paused = False
                        game.advance_event.set()

            elif action == "remove_player":
                code = normalize_code(data.get("game_code"))
                pid = normalize_pid(data.get("player_id"))

                if not code or code not in games:
                    await send_json(websocket, {"type": "error", "message": "Game not found"})
                    continue

                game = games[code]
                if game.teacher_websocket is not websocket:
                    await send_json(websocket, {"type": "error", "message": "Only the teacher can remove players"})
                    continue

                ok, name, target_ws = game.remove_player(pid)
                if ok:
                    print(f"[{code}] Teacher removed player: {name} ({pid})")
                    if target_ws:
                        await send_json(target_ws, {
                            "type": "kicked",
                            "player_id": pid,
                            "message": "You were removed from the session by the teacher.",
                        })
                    await broadcast_game_state(code)
                else:
                    await send_json(websocket, {"type": "error", "message": "Player not found"})

            elif action == "live_typing":
                code = normalize_code(data.get("game_code"))
                pid = normalize_pid(data.get("player_id"))
                current_input = data.get("current_input", "")
                if code in games:
                    game = games[code]
                    if game.phase == "playing" and not game.paused and pid in game.players:
                        game.players[pid]["live_input"] = current_input
                        if game.teacher_websocket:
                            await send_json(game.teacher_websocket, {
                                "type": "student_typing_update",
                                "player_id": pid,
                                "player_name": game.players[pid]["name"],
                                "current_input": current_input,
                            })

            elif action == "submit_answer":
                code = normalize_code(data.get("game_code"))
                pid = normalize_pid(data.get("player_id"))
                answer = (data.get("answer") or "").strip()
                if code in games:
                    game = games[code]
                    if game.paused:
                        await send_json(websocket, {"type": "error", "message": "Game is paused"})
                        continue
                    if game.phase == "playing" and pid in game.players:
                        if not game.players[pid].get("answered"):
                            game.players[pid]["last_answer"] = answer
                            game.players[pid]["live_input"] = answer
                            game.players[pid]["answered"] = True
                            await broadcast_game_state(code)

            elif action == "get_game_state":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    is_teacher = game.teacher_websocket is websocket
                    await send_json(websocket, {
                        "type": "game_state",
                        "game_state": game.get_state(for_teacher=is_teacher),
                    })

            elif action == "reset_game":
                code = normalize_code(data.get("game_code"))
                if code in games:
                    game = games[code]
                    if game.teacher_websocket is websocket:
                        game._stop_requested = True
                        if game._round_task and not game._round_task.done():
                            game._round_task.cancel()
                        game._round_task = None
                        game.advance_event.set()
                        game.phase = "lobby"
                        game.paused = False
                        game.paused_remaining = 0.0
                        game.current_round = 0
                        game.words = []
                        game.last_results = {}
                        game.ranking = []
                        for p in game.players.values():
                            p["score"] = 0
                            p["answered"] = False
                            p["last_answer"] = None
                            p["live_input"] = ""
                        sync_student_txt()
                        await broadcast_game_state(code)
                        print(f"[{code}] Stopped & reset to lobby")

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Handler error: {e}")
    finally:
        if client_id in connections:
            del connections[client_id]

        for code, game in list(games.items()):
            if game.teacher_websocket is websocket:
                game.teacher_websocket = None
            for pid, p in list(game.players.items()):
                if p["websocket"] is websocket:
                    del game.players[pid]
                    if pid in game.last_results:
                        del game.last_results[pid]
                    sync_student_txt()
                    asyncio.create_task(broadcast_game_state(code))


def run_http_server():
    os.chdir(BASE_DIR)
    server = HTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("HTTP Server  -> http://0.0.0.0:8000")
    server.serve_forever()


async def main():
    sync_student_txt()
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    async with websockets.serve(handle_websocket, "0.0.0.0", 8001):
        print("WebSocket    -> ws://0.0.0.0:8001")
        print("Teacher      -> http://localhost:8000/teacher.html")
        print("Students     -> http://localhost:8000/student.html")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")-