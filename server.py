#!/usr/bin/env python3
"""
Typing Bee Server
A local network typing competition application for classrooms
No authentication, no ads, no external dependencies
"""

import asyncio
import websockets
import json
import random
import string
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import os

# Game state
games = {}
connections = {}

# Sample sentences for typing practice - Topic: Fast Cars (~30 words each)
SENTENCES = [
    "The Bugatti Chiron is one of the fastest cars ever made. It can reach speeds over two hundred miles per hour. This amazing car costs more than three million dollars.",
    "Race car drivers need quick reflexes and steady hands. They practice for years to master high speed turns. Safety equipment like helmets and fire suits protect them during crashes.",
    "Electric cars are becoming faster every year. The Tesla Model S can accelerate from zero to sixty in under two seconds. Battery technology keeps improving to make these cars even quicker.",
    "The famous Lamborghini brand makes some of the most exciting sports cars in the world. Their engines roar loudly and their designs look like something from a science fiction movie.",
    "Formula One racing features the fastest cars on any track. These vehicles use advanced technology and lightweight materials. Pit crews can change all four tires in less than three seconds.",
    "Muscle cars from the nineteen sixties and seventies are still popular today. The Ford Mustang and Chevrolet Camaro became American icons. Many collectors restore these classic vehicles to perfect condition.",
    "Drag racing tests which car can cover a quarter mile the fastest. Top fuel dragsters reach over three hundred miles per hour. The races last only a few exciting seconds.",
    "The Porsche nine eleven has been a legendary sports car for decades. It features a unique rear engine design that improves handling. Many racing champions learned to drive in a Porsche.",
    "Supercars use carbon fiber bodies to reduce weight and increase speed. Lighter cars can accelerate faster and handle better around corners. This special material is stronger than steel but much lighter.",
    "NASCAR races happen on oval tracks across America. Drivers compete at speeds near two hundred miles per hour for hours. Teamwork between drivers and pit crews determines who wins each race.",
    "The McLaren company builds both racing cars and street legal supercars. Their vehicles feature cutting edge aerodynamics and powerful engines. Each car takes hundreds of hours to build by hand.",
    "Japan produces many fast and reliable sports cars. The Nissan GTR and Toyota Supra are favorites among car enthusiasts. These vehicles offer amazing performance at prices lower than European competitors.",
    "Wind tunnels help engineers design faster and more efficient cars. Air resistance slows vehicles down at high speeds. Smooth shapes and special spoilers help cars cut through the air more easily.",
    "The Hennessey Venom holds records for incredible straight line speed. This Texas built hypercar combines American muscle with modern technology. Only a handful of these rare machines exist in the world.",
    "Learning to drive a fast car safely takes patience and practice. Professional driving schools teach techniques for handling high performance vehicles. Respecting the power of these machines keeps everyone safe on the road.",
]

class Game:
    def __init__(self, game_id, teacher_websocket=None):
        self.game_id = game_id
        self.sentence = random.choice(SENTENCES)
        self.players = {}
        self.started = False
        self.finished = False
        self.start_time = None
        self.teacher_websocket = teacher_websocket  # Track teacher's connection
        
    def add_player(self, player_name, websocket):
        player_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        self.players[player_id] = {
            'name': player_name,
            'websocket': websocket,
            'progress': 0,
            'completed': False,
            'wpm': 0,
            'accuracy': 0,
            'finish_time': None
        }
        return player_id
    
    def start_game(self):
        self.started = True
        self.start_time = datetime.now()
    
    def update_progress(self, player_id, progress, wpm, accuracy, completed):
        if player_id in self.players:
            self.players[player_id]['progress'] = progress
            self.players[player_id]['wpm'] = wpm
            self.players[player_id]['accuracy'] = accuracy
            if completed and not self.players[player_id]['completed']:
                self.players[player_id]['completed'] = True
                self.players[player_id]['finish_time'] = datetime.now()
    
    def get_state(self):
        return {
            'game_id': self.game_id,
            'sentence': self.sentence,
            'started': self.started,
            'finished': self.finished,
            'players': {
                pid: {
                    'name': p['name'],
                    'progress': p['progress'],
                    'completed': p['completed'],
                    'wpm': p['wpm'],
                    'accuracy': p['accuracy']
                }
                for pid, p in self.players.items()
            }
        }

def generate_game_code():
    """Generate a 6-character game code"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def handle_websocket(websocket):
    """Handle WebSocket connections from students and teachers"""
    client_id = id(websocket)
    connections[client_id] = websocket
    
    # Get client address for logging
    try:
        remote_address = websocket.remote_address
        print(f"New WebSocket connection from {remote_address}")
    except:
        print(f"New WebSocket connection from unknown address")
    
    try:
        async for message in websocket:
            print(f"Received message: {message[:100]}...")  # Print first 100 chars
            data = json.loads(message)
            action = data.get('action')
            print(f"Action: {action}")
            
            if action == 'create_game':
                # Teacher creates a new game
                game_code = generate_game_code()
                while game_code in games:
                    game_code = generate_game_code()
                
                games[game_code] = Game(game_code, teacher_websocket=websocket)
                
                await websocket.send(json.dumps({
                    'type': 'game_created',
                    'game_code': game_code,
                    'sentence': games[game_code].sentence
                }))
            
            elif action == 'join_game':
                # Student joins a game
                game_code = data.get('game_code', '').upper()
                player_name = data.get('player_name', 'Anonymous')
                
                print(f"Join attempt: {player_name} trying to join {game_code}")
                print(f"Available games: {list(games.keys())}")
                
                if game_code in games:
                    game = games[game_code]
                    print(f"Game found! Started: {game.started}")
                    if not game.started:
                        player_id = game.add_player(player_name, websocket)
                        print(f"Player added with ID: {player_id}")
                        
                        response = {
                            'type': 'joined',
                            'player_id': player_id,
                            'game_state': game.get_state()
                        }
                        print(f"Sending response: {json.dumps(response)[:200]}")
                        
                        await websocket.send(json.dumps(response))
                        
                        # Broadcast to all players in this game
                        print(f"Broadcasting game state to all players...")
                        await broadcast_game_state(game_code)
                    else:
                        print("Game already started - rejecting join")
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': 'Game already started'
                        }))
                else:
                    print(f"Game not found! Code: {game_code}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Game not found'
                    }))
            
            elif action == 'start_game':
                # Teacher starts the game
                game_code = data.get('game_code', '').upper()
                if game_code in games:
                    game = games[game_code]
                    game.start_game()
                    await broadcast_game_state(game_code)
            
            elif action == 'update_progress':
                # Student updates their typing progress
                game_code = data.get('game_code', '').upper()
                player_id = data.get('player_id')
                
                if game_code in games:
                    game = games[game_code]
                    game.update_progress(
                        player_id,
                        data.get('progress', 0),
                        data.get('wpm', 0),
                        data.get('accuracy', 0),
                        data.get('completed', False)
                    )
                    await broadcast_game_state(game_code)
            
            elif action == 'get_game_state':
                # Anyone requests current game state
                game_code = data.get('game_code', '').upper()
                if game_code in games:
                    game = games[game_code]
                    await websocket.send(json.dumps({
                        'type': 'game_state',
                        'game_state': game.get_state()
                    }))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Clean up on disconnect
        del connections[client_id]

async def broadcast_game_state(game_code):
    """Broadcast game state to all players AND the teacher in a game"""
    if game_code not in games:
        print(f"Cannot broadcast - game {game_code} not found")
        return
    
    game = games[game_code]
    message = json.dumps({
        'type': 'game_state',
        'game_state': game.get_state()
    })
    
    print(f"Broadcasting to {len(game.players)} players in game {game_code}")
    
    # Send to teacher first
    if game.teacher_websocket:
        try:
            await game.teacher_websocket.send(message)
            print(f"  ✓ Sent to teacher")
        except Exception as e:
            print(f"  ✗ Failed to send to teacher: {e}")
    
    # Send to all players in this game
    sent_count = 0
    for player_id, player in game.players.items():
        try:
            await player['websocket'].send(message)
            sent_count += 1
            print(f"  ✓ Sent to {player['name']}")
        except Exception as e:
            print(f"  ✗ Failed to send to {player['name']}: {e}")

def run_http_server():
    """Run HTTP server for static files"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(('0.0.0.0', 8000), SimpleHTTPRequestHandler)
    print("HTTP Server running on http://0.0.0.0:8000")
    server.serve_forever()

async def main():
    """Start the WebSocket server"""
    print("=" * 60)
    print("TYPING BEE SERVER")
    print("=" * 60)
    print("\nStarting servers...")
    
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    # Start WebSocket server
    server = await websockets.serve(handle_websocket, "0.0.0.0", 8001)
    print("WebSocket Server running on ws://0.0.0.0:8001")
    print("\n" + "=" * 60)
    print("READY!")
    print("=" * 60)
    print("\nTeacher: Open http://localhost:8000/teacher.html")
    print("Students: Open http://localhost:8000/student.html")
    print("\nOr use your computer's IP address to connect from other devices")
    print("=" * 60 + "\n")
    
    await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
