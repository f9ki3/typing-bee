#!/bin/bash

# Typing Bee Startup Script
# Double-click this file to start the server

echo "=========================================="
echo "  TYPING BEE SERVER"
echo "=========================================="
echo ""

# Check if websockets module is installed
python3 -c "import websockets" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "⚠️  Installing required dependencies..."
    echo ""
    python3 -m pip install websockets --user
    echo ""
fi

echo "🚀 Starting Typing Bee Server..."
echo ""

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to that directory
cd "$DIR"

# Get IP address
IP=$(ipconfig getifaddr en0 2>/dev/null)
if [ -z "$IP" ]; then
    IP=$(ipconfig getifaddr en1 2>/dev/null)
fi

echo "📡 Your IP Address: $IP"
echo ""
echo "👨‍🏫 Teacher: Open http://localhost:8000/teacher.html"
echo "👩‍🎓 Students: Open http://$IP:8000/student.html"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=========================================="
echo ""

# Run the server
python3 server.py
