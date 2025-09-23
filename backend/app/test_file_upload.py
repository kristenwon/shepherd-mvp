# test_client.py
import asyncio
import websockets
import json
import sys
import os
import zipfile
from datetime import datetime

class WebSocketFileClient:
    def __init__(self, uri="ws://localhost:8080/ws"):
        self.uri = uri
    
    async def send_file(self, filepath):
        """Send a file via WebSocket"""
        if not os.path.exists(filepath):
            print(f"Error: File {filepath} not found")
            return
        
        try:
            async with websockets.connect(self.uri) as websocket:
                print(f"Connected to {self.uri}")
                
                # Read file as binary
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                file_size = len(file_data)
                print(f"Sending file: {filepath}")
                print(f"File size: {file_size} bytes")
                
                # Send raw binary - exactly like React would
                await websocket.send(file_data)
                print(f"✓ Sent {file_size} bytes")
                
                # Wait for response
                response = await websocket.recv()
                response_data = json.loads(response)
                
                print("\n📥 Server Response:")
                print(f"  Status: {response_data.get('status')}")
                print(f"  Saved as: {response_data.get('filename')}")
                print(f"  Valid ZIP: {response_data.get('is_valid_zip')}")
                
                if response_data.get('contents'):
                    print(f"  ZIP contents: {response_data.get('contents')}")
                
                return response_data
                
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    async def send_json(self, data):
        """Send JSON data via WebSocket"""
        try:
            async with websockets.connect(self.uri) as websocket:
                print(f"Connected to {self.uri}")
                
                # Send JSON
                json_str = json.dumps(data)
                await websocket.send(json_str)
                print(f"Sent JSON: {json_str}")
                
                # Wait for response
                response = await websocket.recv()
                response_data = json.loads(response)
                print(f"Response: {response_data}")
                
                return response_data
                
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    async def send_multiple_files(self, filepaths):
        """Send multiple files in sequence"""
        for filepath in filepaths:
            print(f"\n{'='*50}")
            await self.send_file(filepath)
            await asyncio.sleep(1)  # Wait between sends

def create_test_zip(filename="test.zip"):
    """Create a test ZIP file"""
    with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add some test files to the ZIP
        zf.writestr('readme.txt', 'This is a test ZIP file')
        zf.writestr('data.json', json.dumps({"test": "data", "timestamp": datetime.now().isoformat()}))
        zf.writestr('config.ini', '[settings]\nkey=value\ntest=true')
    
    print(f"Created test ZIP file: {filename}")
    
    # Print ZIP info
    with zipfile.ZipFile(filename, 'r') as zf:
        print(f"ZIP contents: {zf.namelist()}")
        print(f"ZIP size: {os.path.getsize(filename)} bytes")
    
    return filename

async def run_tests():
    """Run comprehensive tests"""
    client = WebSocketFileClient()
    
    print("🧪 WebSocket File Upload Test Suite")
    print("="*50)
    
    # Test 1: Create and send a test ZIP
    print("\n📝 Test 1: Send ZIP file")
    test_file = create_test_zip("test.zip")
    await client.send_file(test_file)
    
    # Test 2: Send JSON data
    print("\n📝 Test 2: Send JSON data")
    test_data = {
        "type": "metadata",
        "filename": "upcoming_file.zip",
        "size": 1024
    }
    await client.send_json(test_data)
    
    # Test 3: Create multiple test ZIPs and send them
    print("\n📝 Test 3: Send multiple ZIP files")
    files = []
    for i in range(3):
        filename = f"test_{i}.zip"
        with zipfile.ZipFile(filename, 'w') as zf:
            zf.writestr(f'file_{i}.txt', f'This is file {i}')
        files.append(filename)
    
    await client.send_multiple_files(files)
    
    # Cleanup
    print("\n🧹 Cleaning up test files...")
    for f in files + [test_file]:
        if os.path.exists(f):
            os.remove(f)
            print(f"  Removed {f}")

async def interactive_client():
    """Interactive client for manual testing"""
    client = WebSocketFileClient()
    
    while True:
        print("\n" + "="*50)
        print("WebSocket File Client")
        print("1. Send ZIP file")
        print("2. Create and send test ZIP")
        print("3. Send JSON message")
        print("4. Run automated tests")
        print("5. Exit")
        
        choice = input("\nSelect option: ").strip()
        
        if choice == "1":
            filepath = input("Enter ZIP file path: ").strip()
            await client.send_file(filepath)
            
        elif choice == "2":
            filename = input("Enter filename for test ZIP (default: test.zip): ").strip() or "test.zip"
            test_file = create_test_zip(filename)
            await client.send_file(test_file)
            
        elif choice == "3":
            json_str = input("Enter JSON (e.g., {\"key\": \"value\"}): ").strip()
            try:
                data = json.loads(json_str)
                await client.send_json(data)
            except json.JSONDecodeError:
                print("Invalid JSON format")
                
        elif choice == "4":
            await run_tests()
            
        elif choice == "5":
            print("Goodbye!")
            break
        
        else:
            print("Invalid option")

if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            # Run automated tests
            asyncio.run(run_tests())
        elif sys.argv[1] == "interactive":
            # Run interactive client
            asyncio.run(interactive_client())
        else:
            # Send specific file
            asyncio.run(WebSocketFileClient().send_file(sys.argv[1]))
    else:
        print("Usage:")
        print("  python test_client.py test           # Run automated tests")
        print("  python test_client.py interactive    # Interactive mode")
        print("  python test_client.py <filepath>     # Send specific file")
        print("\nDefaulting to automated tests...")
        asyncio.run(run_tests())