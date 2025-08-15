#!/usr/bin/env python3
"""
Server startup script for the RPG Game API
"""
import uvicorn
from config import HOST, PORT, DEBUG

if __name__ == "__main__":
    print(f"🚀 Starting RPG Game API server...")
    print(f"📍 Host: {HOST}")
    print(f"🔌 Port: {PORT}")
    print(f"🐛 Debug: {DEBUG}")
    print(f"📚 API Docs: http://{HOST}:{PORT}/docs")
    print(f"🔍 Health Check: http://{HOST}:{PORT}/health")
    print("\nPress Ctrl+C to stop the server")
    
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="info" if DEBUG else "warning"
    )
