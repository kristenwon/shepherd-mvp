# server.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
from datetime import datetime
import os
from typing import Optional
import zipfile
import io

app = FastAPI()

# Create uploads directory if it doesn't exist
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"Client disconnected. Total connections: {len(self.active_connections)}")

    async def send_json(self, websocket: WebSocket, data: dict):
        await websocket.send_json(data)

manager = ConnectionManager()

@app.get("/test-upload-zip-file")
async def get():
    """Serve a simple HTML page for testing"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket File Upload Test</title>
    </head>
    <body>
        <h1>WebSocket File Upload Test</h1>
        <input type="file" id="fileInput" accept=".zip">
        <button onclick="sendFile()">Send ZIP</button>
        <div id="status"></div>
        
        <script>
            const ws = new WebSocket("ws://localhost:8080/ws");
            
            ws.onmessage = (event) => {
                document.getElementById('status').innerHTML = event.data;
            };
            
            function sendFile() {
                const file = document.getElementById('fileInput').files[0];
                if (file) {
                    ws.send(file);
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    try:
        while True:
            # Receive data from client
            data = await websocket.receive()
            
            # Check if it's binary data (ZIP file)
            if "bytes" in data:
                binary_data = data["bytes"]
                
                # Generate filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"received_{timestamp}.zip"
                filepath = os.path.join(UPLOAD_DIR, filename)
                
                # Save the file
                with open(filepath, 'wb') as f:
                    f.write(binary_data)
                
                print(f"Received binary file: {filename}")
                print(f"Size: {len(binary_data)} bytes")
                
                # Verify it's a valid ZIP file
                is_valid_zip = False
                zip_contents = []
                
                try:
                    with zipfile.ZipFile(io.BytesIO(binary_data), 'r') as zf:
                        is_valid_zip = True
                        zip_contents = zf.namelist()
                        print(f"ZIP contents: {zip_contents}")
                except zipfile.BadZipFile:
                    print("Warning: File is not a valid ZIP")
                
                # Send response back to client
                response = {
                    "status": "success",
                    "message": f"File received successfully",
                    "filename": filename,
                    "size": len(binary_data),
                    "saved_to": filepath,
                    "is_valid_zip": is_valid_zip,
                    "contents": zip_contents if is_valid_zip else [],
                    "timestamp": timestamp
                }
                
                await manager.send_json(websocket, response)
                
            # Check if it's text/JSON data
            elif "text" in data:
                text_data = data["text"]
                
                try:
                    # Try to parse as JSON
                    json_data = json.loads(text_data)
                    print(f"Received JSON: {json_data}")
                    
                    response = {
                        "status": "received",
                        "type": "json",
                        "data": json_data
                    }
                    
                except json.JSONDecodeError:
                    # Plain text
                    print(f"Received text: {text_data}")
                    response = {
                        "status": "received",
                        "type": "text",
                        "data": text_data
                    }
                
                await manager.send_json(websocket, response)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("Client disconnected")
    except Exception as e:
        print(f"Error: {e}")
        manager.disconnect(websocket)

# Additional endpoint to list uploaded files
@app.get("/uploads")
async def list_uploads():
    """List all uploaded files"""
    files = []
    for filename in os.listdir(UPLOAD_DIR):
        filepath = os.path.join(UPLOAD_DIR, filename)
        if os.path.isfile(filepath):
            files.append({
                "filename": filename,
                "size": os.path.getsize(filepath),
                "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
            })
    return {"files": files}

if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI WebSocket server...")
    print("WebSocket endpoint: ws://localhost:8080/ws")
    print("Web interface: http://localhost:8080")
    print("Uploaded files will be saved to: ./uploads/")
    uvicorn.run(app, host="0.0.0.0", port=8080)