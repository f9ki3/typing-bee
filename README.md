# Typing Bee 🏆

A local network typing competition application designed for middle school classrooms.

## Features

✅ **No Authentication** - Students just enter their name and join  
✅ **No Internet Required** - Runs completely on your local network  
✅ **No Ads** - Clean, distraction-free interface  
✅ **No External Services** - Everything runs on your computer  
✅ **Real-time Competition** - Live WPM and accuracy tracking  
✅ **Kahoot-style Join Codes** - Students join with a simple 6-character code  
✅ **Teacher Control Panel** - Start games and view live results  

## ⚠️ Known Issue: Browser Security & Local Network Connections

**Important:** Modern browsers (Chrome, Safari, Firefox, Edge) have security features that may block WebSocket connections to local network servers. This can cause some student devices to hang or fail to connect.

### What Students May See:
- A browser popup asking to "Allow" connections to a local server
- The page hanging on "Connecting to game server..."
- A connection error message

### Solutions:
1. **Students must click "Allow"** when their browser asks for permission
2. Look for a shield icon or popup near the browser's address bar
3. On some devices, check browser settings for "Local Network" or "Private Network" permissions
4. **Chrome** usually handles this best - recommend Chrome over Safari for student devices
5. **iPads/iPhones with Safari** may have the most issues - try Chrome for iOS instead

### Before Class:
- Have all students load the student page first
- Verify everyone sees the green "✅ Connected!" message
- THEN create the game code and have students join

---

## Requirements

- Python 3.7+ (comes pre-installed on macOS)
- Any modern web browser (Chrome recommended)
- All devices must be on the same Wi-Fi network

---

## Complete Setup Instructions

### Step 1: Create the Project Folder

Create a folder called `typing-bee` on your Desktop. Place all the project files inside:
- `server.py`
- `teacher.html`
- `student.html`
- `start.sh` (optional)
- `README.md` (this file)

Your folder structure should look like:
```
Desktop/
  typing-bee/
    server.py
    teacher.html
    student.html
    start.sh
    README.md
```

### Step 2: Install the WebSockets Module

Open **Terminal** (on Mac: Applications → Utilities → Terminal) and run:

```bash
pip3 install websockets --user
```

If you get a "command not found" error, try:

```bash
python3 -m pip install websockets --user
```

You only need to do this once. The websockets module enables real-time communication between the server and all connected browsers.

### Step 3: Start the Server

In Terminal, run these commands:

```bash
cd ~/Desktop/typing-bee && python3 server.py
```

**Note:** If your folder is in a different location, adjust the path accordingly. For example:
- Documents folder: `cd ~/Documents/typing-bee && python3 server.py`
- Downloads folder: `cd ~/Downloads/typing-bee && python3 server.py`

You should see output like this:

```
============================================================
TYPING BEE SERVER
============================================================

Starting servers...
HTTP Server running on http://0.0.0.0:8000
WebSocket Server running on ws://0.0.0.0:8001

============================================================
READY!
============================================================

Teacher: Open http://localhost:8000/teacher.html
Students: Open http://localhost:8000/student.html

Or use your computer's IP address to connect from other devices
============================================================
```

**Keep this Terminal window open!** Closing it will stop the server.

### Step 4: Find Your Computer's IP Address

Students need your computer's IP address to connect. Find it using one of these methods:

**Option A - Terminal command:**
```bash
ipconfig getifaddr en0
```
This will display something like `192.168.1.50`

**Option B - System Preferences:**
1. Open System Preferences → Network
2. Select your Wi-Fi connection
3. Your IP address is displayed (e.g., 192.168.1.50)

### Step 5: Open the Teacher Interface

On your computer (the one running the server), open a web browser and go to:

```
http://localhost:8000/teacher.html
```

### Step 6: Have Students Connect

Write the student URL on the board, replacing `[YOUR-IP]` with your actual IP address:

```
http://[YOUR-IP]:8000/student.html
```

**Example:** `http://192.168.1.50:8000/student.html`

Students should:
1. Open this URL in their browser (Chrome recommended)
2. Wait for the green "✅ Connected!" message
3. If prompted by their browser, click "Allow" to permit the connection

### Step 7: Create and Start a Game

**Teacher:**
1. Click "Create New Game" on the teacher interface
2. A 6-character game code will appear (e.g., `VW0S9J`)
3. Display this code on your projector for students to see

**Students:**
1. Enter their name
2. Enter the 6-character game code
3. Click "Join Game"

**Teacher:**
4. Watch the player list update as students join
5. Once everyone has joined, click "Start Race"
6. Watch the live leaderboard update in real-time!

### Step 8: After the Race

- Click "Reset Everything" to start completely fresh with a new game code
- Students will need to rejoin after a reset

---

## Customization

### Add Your Own Sentences

Edit `server.py` and modify the `SENTENCES` list (around line 20):

```python
SENTENCES = [
    "Your custom sentence here.",
    "Another sentence for students to type.",
    "Add as many as you want!",
]
```

Save the file and restart the server for changes to take effect.

### Change Styling

- Edit `teacher.html` to customize the teacher interface
- Edit `student.html` to customize the student interface
- Look for the `<style>` sections to change colors, fonts, sizes, etc.

---

## Troubleshooting

### Students can't connect / page hangs

1. **Browser security:** Students may need to click "Allow" on a browser permission popup
2. **Same network:** Verify all devices are on the same Wi-Fi network
3. **Firewall:** On Mac, you may see a popup asking to allow Python - click "Allow"
4. **Correct IP:** Double-check you're using the right IP address
5. **Test locally first:** Try `http://localhost:8000/student.html` on your own computer

### "pip3: command not found"

Try this alternative command:
```bash
python3 -m pip install websockets --user
```

### "Module not found: websockets"

The websockets module didn't install correctly. Try:
```bash
python3 -m pip install --user websockets
```

### Port already in use

If you see an error about port 8000 or 8001 already being in use:
- You may have another server running - check for other Terminal windows
- Restart your computer, or
- Find and kill the process using that port

### Server won't start

Make sure you're in the correct directory:
```bash
cd ~/Desktop/typing-bee
ls
```
You should see `server.py` in the file list. Then run:
```bash
python3 server.py
```

---

## How It Works

- **Server (`server.py`)**: Python WebSocket server that manages game state
- **Teacher Interface (`teacher.html`)**: Control panel for creating/starting games
- **Student Interface (`student.html`)**: Join games and compete in real-time
- **Communication**: WebSockets provide real-time updates to all clients

---

## Privacy & Security

✅ All data stays on your local network  
✅ No data is sent to external servers  
✅ No student accounts or passwords required  
✅ No tracking or analytics  
✅ Game data is cleared when server restarts  

---

## Tips for Classroom Use

1. **Test before class** - Run through a complete game yourself first
2. **Use Chrome** - It handles local network connections most reliably
3. **Check connections first** - Have all students confirm "✅ Connected!" before creating a game
4. **Project the teacher screen** - Students love seeing the live leaderboard
5. **Pre-write the URL** on the board: `http://[your-ip]:8000/student.html`
6. **Warm-up round** - Do a practice game so students understand the flow
7. **Custom sentences** - Match typing content to your curriculum

---

## License

MIT License - Free to use and modify for educational purposes!

---

Vibe Coded by [Wes Fryer](https://wesfryer.com/) - [GitHub](https://github.com/wfryer?tab=repositories) - [AI Experiments](https://ai.wesfryer.com/)
