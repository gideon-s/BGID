# WebSocket Broadcasting Troubleshooting Guide

## 🚨 **Common Issue: No Real-Time Updates**

### **Problem**: Running two terminals but not seeing broadcast messages

### **Root Cause**: Using wrong CLI client
- ❌ **`cli.py`** - Regular CLI without WebSocket functionality
- ✅ **`websocket_cli.py`** - WebSocket-enabled CLI with real-time updates

## 🔧 **Solution: Use Correct Commands**

### **Terminal 1 - Player 1:**
```bash
cd /home/bryanj/app
source venv/bin/activate
python websocket_cli.py --player 1
```

### **Terminal 2 - Player 2:**
```bash
cd /home/bryanj/app
source venv/bin/activate
python websocket_cli.py --player 2
```

## ✅ **What to Look For**

### **Successful Connection:**
```
✅ Connected to WebSocket as Player 1
==================================================
 Welcome to the WebSocket Game CLI! 
==================================================
ℹ️  Real-time updates will appear automatically!
```

### **Real-Time Updates Appear As:**
```
🔴 [REAL-TIME] Player Wizard joined the room
🔴 [REAL-TIME] Player Wizard left the room
🔴 [REAL-TIME] Player Wizard moved to Dark Forest
```

## 🧪 **Testing Real-Time Updates**

### **Step 1: Connect Both Players**
- Start both terminals with `websocket_cli.py`
- Verify both show "✅ Connected to WebSocket"

### **Step 2: Trigger Events**
- In Player 2's terminal: `/go Dark Forest`
- Watch Player 1's terminal for real-time updates

### **Step 3: Verify Broadcasting**
- Player 1 should see: `🔴 [REAL-TIME] Player Wizard left the room`
- Player 2 should see: `🔴 [REAL-TIME] You moved to Dark Forest`

## 🔍 **Troubleshooting Steps**

### **1. Check Server Status**
```bash
curl http://localhost:8000/
# Should return: {"message": "Welcome to the Game API!"}
```

### **2. Verify WebSocket Endpoints**
```bash
# Check if WebSocket endpoint is accessible
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
     -H "Sec-WebSocket-Version: 13" \
     http://localhost:8000/ws/1
```

### **3. Check Active Connections**
```bash
lsof -i :8000
# Should show uvicorn and python processes
```

### **4. Restart Server if Needed**
```bash
pkill -f "uvicorn\|python.*main.py"
cd /home/bryanj/app
source venv/bin/activate
python main.py
```

## 🎯 **Expected Behavior**

### **When Player 2 Connects:**
- Player 1 sees: `🔴 [REAL-TIME] Player Wizard joined the room`
- Player 2 sees: `✅ Connected to WebSocket as Player 2`

### **When Player 2 Moves:**
- Player 1 sees: `🔴 [REAL-TIME] Player Wizard left the room`
- Player 2 sees: `🔴 [REAL-TIME] You moved to Dark Forest`

### **When Player 2 Returns:**
- Player 1 sees: `🔴 [REAL-TIME] Player Wizard joined the room`
- Player 2 sees: `🔴 [REAL-TIME] You entered The Rusty Tavern`

## 🚫 **Common Mistakes**

1. **Using `cli.py` instead of `websocket_cli.py`**
2. **Not activating virtual environment**
3. **Server not running**
4. **Port conflicts (8000 already in use)**
5. **Wrong working directory**

## ✅ **Quick Test Commands**

```bash
# Kill any existing processes
pkill -f "python.*cli.py"

# Start server (if not running)
cd /home/bryanj/app && source venv/bin/activate && python main.py

# In Terminal 1
python websocket_cli.py --player 1

# In Terminal 2  
python websocket_cli.py --player 2

# Test movement in Terminal 2
/go Dark Forest
```

## 🎉 **Success Indicators**

- ✅ Both terminals show "Connected to WebSocket"
- ✅ Real-time updates appear automatically
- ✅ Player movements trigger instant notifications
- ✅ Both players see each other's actions

## 🔗 **Need More Help?**

If you're still not seeing real-time updates:
1. Check the troubleshooting steps above
2. Verify you're using `websocket_cli.py` (not `cli.py`)
3. Ensure both players show "Connected to WebSocket"
4. Try moving players between rooms to trigger events
