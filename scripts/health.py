import asyncio
import json
import logging
from datetime import datetime
import psutil
import os

logger = logging.getLogger(__name__)

class SimpleHealthServer:
    def __init__(self, port=8000):
        self.port = port
        self.start_time = datetime.now()

    async def handle_request(self, reader, writer):
        try:
            request = await reader.read(1024)
            memory = psutil.virtual_memory()
            uptime = datetime.now() - self.start_time
            
            health_data = {
                "status": "healthy",
                "service": "terabox_leech_bot",
                "uptime_seconds": uptime.total_seconds(),
                "memory_available_mb": round(memory.available / (1024 * 1024), 2)
            }
            
            response_body = json.dumps(health_data)
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Connection: close\r\n\r\n"
                f"{response_body}"
            )
            
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            logger.warning(f"Health server error: {e}")

    async def start(self):
        server = await asyncio.start_server(self.handle_request, '0.0.0.0', self.port)
        logger.info(f"Health server listening on port {self.port}")
        async with server:
            await server.serve_forever()

async def run_health_server(port=8000):
    """Main function exported to bot.py"""
    health_server = SimpleHealthServer(port)
    await health_server.start()
        
