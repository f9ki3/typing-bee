import asyncio
import json
import os
import random
import string
import threading
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import websockets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_WORDS = []

DICEBEAR_STYLES = {
    "avataaars",
    "bottts",
    "lorelei",
    "notionists",
    "adventurer",
    "big-smile",
    "fun-emoji",
    "thumbs",
    "identicon",
    "shapes",
}

GAMES = {}
CLIENT_META = {}


def make_avatar_url(style: str | None, seed: str | None) -> str:
    clean_style = (style or "avataaars").strip().lower()
    if clean_style not in DICEBEAR_STYLES:
        clean_style = "avataaars"
    clean_seed = (seed or "player").strip() or "player"
    return (
        f"https://api.dicebear.com/9.x/{clean_style}/svg"
        f"?seed={urllib.parse.quote(clean_seed)}&size=128"
    )


def generate_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=length))
        if code not in GAMES:
            return code


def normalize_round_title(raw_title) -> str:
    if isinstance(raw_title, str):
        cleaned = " ".join(raw_title.strip().split())
        if cleaned:
            return cleaned[:40]
    return "Standard Round"


def normalize_points_per_correct(raw_points) -> int:
    try:
        pts = int(raw_points)
    except (TypeError, ValueError):
        return 1
    return max(1, min(100, pts))


class Game:
    def __init__(self, code: str):
        self.code = code
        self.host_ws = None
        self.phase = "lobby"
        self.previous_phase = "round_result"
        self.paused = False
        self.num_rounds = 5
        self.timer_seconds = 20
        self.round_title = "Standard Round"
        self.points_per_correct = 1

        self.players = {}
        self.word_bank = [dict(w) for w in DEFAULT_WORDS]
        self.round_words = []
        self.current_round = 0
        self.current_word_obj = None
        self.time_left = 0
        self.last_results = {}
        self.ranking = []
        self.countdown_event = asyncio.Event()
        self.advance_event = asyncio.Event()
        self.retry_event = asyncio.Event()
        self.loop_task = None

    def apply_config(self, data: dict):
        if "rounds" in data:
            try:
                r = int(data["rounds"])
                self.num_rounds = max(1, min(50, r))
            except (TypeError, ValueError):
                pass

        if "timer" in data:
            try:
                t = int(data["timer"])
                self.timer_seconds = max(5, min(180, t))
            except (TypeError, ValueError):
                pass

        if "round_title" in data:
            self.round_title = normalize_round_title(data["round_title"])

        if "points_per_correct" in data:
            self.points_per_correct = normalize_points_per_correct(
                data["points_per_correct"]
            )

    def update_word_bank(self, words: list[dict], mode: str = "replace") -> int:
        cleaned = []
        for item in words or []:
            if not isinstance(item, dict):
                continue
            w = str(item.get("word", "")).strip()
            d = str(item.get("definition", "")).strip()
            if w and d:
                cleaned.append({"word": w, "definition": d})
        if not cleaned:
            return len(self.word_bank)

        if mode == "append":
            self.word_bank.extend(cleaned)
        else:
            self.word_bank = cleaned
        return len(self.word_bank)

    def rollback_current_round_points(self):
        if not self.last_results:
            return
        for pid, res in self.last_results.items():
            awarded = int(res.get("points_awarded") or 0)
            if awarded > 0 and pid in self.players:
                self.players[pid]["score"] = max(
                    0, self.players[pid]["score"] - awarded
                )
        self.last_results = {}

    def reset_to_lobby(self):
        if self.loop_task and not self.loop_task.done():
            self.loop_task.cancel()
        self.loop_task = None
        self.countdown_event.clear()
        self.advance_event.clear()
        self.retry_event.clear()
        self.phase = "lobby"
        self.previous_phase = "round_result"
        self.paused = False
        self.current_round = 0
        self.current_word_obj = None
        self.time_left = 0
        self.last_results = {}
        self.ranking = []
        for p in self.players.values():
            p["score"] = 0
            p["answered"] = False
            p["answer"] = ""
            p["live_input"] = ""

    def compute_ranking(self) -> list[dict]:
        ranked = sorted(
            self.players.values(),
            key=lambda p: (-p.get("score", 0), p.get("name", "").lower()),
        )
        return [
            {
                "name": p["name"],
                "score": p["score"],
                "avatar": p.get("avatar"),
            }
            for p in ranked
        ]

    def get_state(self) -> dict:
        word_str = self.current_word_obj["word"] if self.current_word_obj else ""
        def_str = self.current_word_obj["definition"] if self.current_word_obj else ""
        first_letter = word_str[0].upper() if word_str else ""
        letter_count = len(word_str.replace(" ", "")) if word_str else 0

        players_payload = {
            pid: {
                "name": p["name"],
                "score": p["score"],
                "answered": p["answered"],
                "avatar": p.get("avatar"),
                "live_input": p.get("live_input", ""),
            }
            for pid, p in self.players.items()
        }

        state = {
            "game_code": self.code,
            "phase": self.phase,
            "previous_phase": self.previous_phase,
            "paused": self.paused,
            "round_title": self.round_title,
            "points_per_correct": self.points_per_correct,
            "num_rounds": self.num_rounds,
            "timer_seconds": self.timer_seconds,
            "current_round": self.current_round,
            "total_rounds": self.num_rounds,
            "time_left": self.time_left,
            "definition": def_str,
            "first_letter": first_letter,
            "letter_count": letter_count,
            "players": players_payload,
            "word_bank_count": len(self.word_bank),
            "word_list": self.word_bank,
            "ranking": self.compute_ranking(),
        }

        if self.phase in ("round_ready", "countdown", "playing"):
            state["word"] = word_str

        if self.phase in ("round_result", "scores_view"):
            state["correct_word"] = word_str
            state["last_results"] = self.last_results

        if self.phase == "game_over":
            state["ranking"] = self.ranking or self.compute_ranking()

        return state


async def send_json(ws, payload: dict):
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass


async def broadcast_state(game: Game):
    payload = {"type": "game_state", "game_state": game.get_state()}
    dead = []
    for pid, p in game.players.items():
        ws = p.get("ws")
        if ws:
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                dead.append(pid)
    for pid in dead:
        game.players.pop(pid, None)

    if game.host_ws:
        try:
            await game.host_ws.send(json.dumps(payload))
        except Exception:
            pass


async def wait_while_paused(game: Game):
    while game.paused:
        await asyncio.sleep(0.2)


async def run_match(game: Game):
    try:
        pool = game.word_bank if game.word_bank else DEFAULT_WORDS
        game.round_words = [random.choice(pool) for _ in range(game.num_rounds)]

        r_idx = 1
        while r_idx <= game.num_rounds:
            game.current_round = r_idx
            game.current_word_obj = game.round_words[r_idx - 1]
            game.last_results = {}
            game.phase = "round_ready"
            game.time_left = game.timer_seconds
            game.countdown_event.clear()
            game.retry_event.clear()
            game.advance_event.clear()

            for p in game.players.values():
                p["answered"] = False
                p["answer"] = ""
                p["live_input"] = ""

            await broadcast_state(game)

            while not game.countdown_event.is_set() and not game.retry_event.is_set():
                await asyncio.sleep(0.15)

            if game.retry_event.is_set():
                game.retry_event.clear()
                continue

            game.phase = "countdown"
            game.time_left = 3
            await broadcast_state(game)

            cd = 3
            while cd > 0 and not game.retry_event.is_set():
                await wait_while_paused(game)
                game.time_left = cd
                await broadcast_state(game)
                await asyncio.sleep(1)
                cd -= 1

            if game.retry_event.is_set():
                game.retry_event.clear()
                continue

            game.phase = "playing"
            remaining = game.timer_seconds
            game.time_left = remaining
            await broadcast_state(game)

            while remaining > 0 and not game.retry_event.is_set():
                await wait_while_paused(game)
                all_answered = (
                    len(game.players) > 0
                    and all(p.get("answered") for p in game.players.values())
                )
                if all_answered:
                    break
                await asyncio.sleep(1)
                if game.paused or game.retry_event.is_set():
                    continue
                remaining -= 1
                game.time_left = remaining
                await broadcast_state(game)

            if game.retry_event.is_set():
                game.retry_event.clear()
                continue

            target_word = game.current_word_obj["word"].strip().lower()
            pts_value = game.points_per_correct
            round_res = {}

            for pid, p in game.players.items():
                submitted = (p.get("answer") or p.get("live_input") or "").strip()
                is_correct = bool(submitted) and (submitted.lower() == target_word)
                awarded = pts_value if is_correct else 0
                if is_correct:
                    p["score"] += awarded
                round_res[pid] = {
                    "name": p["name"],
                    "avatar": p.get("avatar"),
                    "answer": submitted,
                    "correct": is_correct,
                    "points_awarded": awarded,
                    "score": p["score"],
                }

            game.last_results = round_res
            game.phase = "round_result"
            game.time_left = 0
            game.advance_event.clear()
            game.retry_event.clear()
            await broadcast_state(game)

            while not game.advance_event.is_set() and not game.retry_event.is_set():
                await asyncio.sleep(0.15)
                if game.phase not in ("round_result", "scores_view"):
                    return

            if game.retry_event.is_set():
                game.retry_event.clear()
                game.rollback_current_round_points()
                continue

            r_idx += 1

        game.phase = "game_over"
        game.ranking = game.compute_ranking()
        await broadcast_state(game)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"[Match Error {game.code}] {exc}")


async def handle_websocket(ws):
    CLIENT_META[ws] = {"role": None, "game_code": None, "player_id": None}
    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await send_json(ws, {"type": "error", "message": "Invalid JSON payload"})
                continue

            action = data.get("action")

            if action == "create_game":
                code = generate_code()
                game = Game(code)
                game.host_ws = ws
                GAMES[code] = game
                CLIENT_META[ws] = {"role": "host", "game_code": code, "player_id": None}
                await send_json(
                    ws,
                    {
                        "type": "game_created",
                        "game_code": code,
                        "game_state": game.get_state(),
                    },
                )

            elif action == "get_game_state":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    await send_json(ws, {"type": "error", "message": "Game session not found"})
                    continue
                if CLIENT_META[ws]["role"] == "host":
                    game.host_ws = ws
                await send_json(ws, {"type": "game_state", "game_state": game.get_state()})

            elif action == "set_config":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    await send_json(ws, {"type": "error", "message": "Game session not found"})
                    continue
                if game.phase != "lobby":
                    await send_json(
                        ws,
                        {"type": "error", "message": "Config can only be changed in lobby"},
                    )
                    continue
                game.apply_config(data)
                await broadcast_state(game)

            elif action == "start_game":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    await send_json(ws, {"type": "error", "message": "Game session not found"})
                    continue
                if not game.players:
                    await send_json(
                        ws,
                        {"type": "error", "message": "At least one student must join first"},
                    )
                    continue
                game.apply_config(data)
                if game.loop_task and not game.loop_task.done():
                    game.loop_task.cancel()
                game.paused = False
                game.countdown_event.clear()
                game.advance_event.clear()
                game.retry_event.clear()
                game.loop_task = asyncio.create_task(run_match(game))

            elif action == "start_countdown":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase == "round_ready":
                    game.paused = False
                    game.countdown_event.set()

            elif action == "retry_round":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase in ("round_ready", "countdown", "playing", "round_result", "scores_view"):
                    if game.phase in ("round_result", "scores_view"):
                        game.rollback_current_round_points()
                    game.paused = False
                    game.retry_event.set()
                    await broadcast_state(game)

            elif action == "show_scores":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase in ("round_result", "game_over"):
                    game.previous_phase = game.phase
                    game.ranking = game.compute_ranking()
                    game.phase = "scores_view"
                    await broadcast_state(game)

            elif action == "return_from_scores":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase == "scores_view":
                    target = game.previous_phase if game.previous_phase in ("round_result", "game_over") else "round_result"
                    if target == "game_over":
                        game.ranking = game.compute_ranking()
                    game.phase = target
                    await broadcast_state(game)

            elif action == "toggle_pause":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase in ("round_ready", "countdown", "playing", "round_result"):
                    game.paused = not game.paused
                    await broadcast_state(game)

            elif action == "next_round":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                if game.phase in ("round_result", "scores_view"):
                    game.paused = False
                    game.advance_event.set()

            elif action == "reset_game":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    continue
                game.reset_to_lobby()
                await broadcast_state(game)

            elif action == "remove_player":
                code = (data.get("game_code") or "").strip().upper()
                pid = data.get("player_id")
                game = GAMES.get(code)
                if not game or not pid:
                    continue
                removed = game.players.pop(pid, None)
                if removed and removed.get("ws"):
                    await send_json(
                        removed["ws"],
                        {
                            "type": "kicked",
                            "message": "You were removed from the session by the teacher.",
                        },
                    )
                await broadcast_state(game)

            elif action == "update_word_bank":
                code = (data.get("game_code") or "").strip().upper()
                game = GAMES.get(code)
                if not game:
                    await send_json(ws, {"type": "error", "message": "Game session not found"})
                    continue
                mode = data.get("mode", "replace")
                words = data.get("words", [])
                total = game.update_word_bank(words, mode=mode)
                await send_json(
                    ws,
                    {
                        "type": "word_bank_updated",
                        "mode": mode,
                        "total": total,
                    },
                )
                await broadcast_state(game)

            elif action == "join_game":
                code = (data.get("game_code") or "").strip().upper()
                name = (data.get("player_name") or "").strip()[:20]
                game = GAMES.get(code)
                if not game:
                    await send_json(ws, {"type": "error", "message": "Room code not found"})
                    continue
                if not name:
                    await send_json(ws, {"type": "error", "message": "Please enter your name"})
                    continue

                pid = "P-" + "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=5)
                )
                avatar_url = make_avatar_url(
                    data.get("avatar_style"), data.get("avatar_seed") or name
                )
                game.players[pid] = {
                    "name": name,
                    "score": 0,
                    "answered": False,
                    "answer": "",
                    "live_input": "",
                    "avatar": avatar_url,
                    "ws": ws,
                }
                CLIENT_META[ws] = {"role": "student", "game_code": code, "player_id": pid}
                await send_json(
                    ws,
                    {
                        "type": "joined",
                        "player_id": pid,
                        "game_state": game.get_state(),
                    },
                )
                await broadcast_state(game)

            elif action == "live_typing":
                code = (data.get("game_code") or "").strip().upper()
                pid = data.get("player_id")
                game = GAMES.get(code)
                if not game or game.paused or game.phase != "playing":
                    continue
                p = game.players.get(pid)
                if not p or p.get("answered"):
                    continue
                current_input = str(data.get("current_input") or "")[:60]
                p["live_input"] = current_input
                if game.host_ws:
                    await send_json(
                        game.host_ws,
                        {
                            "type": "student_typing_update",
                            "player_id": pid,
                            "current_input": current_input,
                        },
                    )

            elif action == "submit_answer":
                code = (data.get("game_code") or "").strip().upper()
                pid = data.get("player_id")
                game = GAMES.get(code)
                if not game or game.paused or game.phase != "playing":
                    continue
                p = game.players.get(pid)
                if not p or p.get("answered"):
                    continue
                ans = str(data.get("answer") or "").strip()[:60]
                p["answer"] = ans
                p["live_input"] = ans
                p["answered"] = True
                await broadcast_state(game)

    except websockets.ConnectionClosed:
        pass
    finally:
        meta = CLIENT_META.pop(ws, None)
        if meta and meta.get("role") == "student":
            game = GAMES.get(meta.get("game_code") or "")
            pid = meta.get("player_id")
            if game and pid and pid in game.players:
                game.players[pid]["ws"] = None


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def run_http_server():
    os.chdir(BASE_DIR)
    server = ReusableHTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("HTTP Server  -> http://0.0.0.0:8000")
    server.serve_forever()


async def main():
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print("WS Server    -> ws://0.0.0.0:8001")
    async with websockets.serve(handle_websocket, "0.0.0.0", 8001):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")