# services/health.py

import asyncio
import json
import logging
from datetime import datetime
import psutil
import os

logger = logging.getLogger(__name__)

class HealthServer:
    """Enhanced health check server for Koyeb deployment"""
    
    def __init__(self, port=8000):
        self.port = port
        self.should_exit = False
        self.start_time = datetime.now()
    
    async def handle_request(self, reader, writer):
        """Handle HTTP requests"""
        try:
            # Read request
            request = await reader.read(1024)
            request_str = request.decode('utf-8')
            
            # Parse request path
            if 'GET /' in request_str and 'health' in request_str:
                response = await self.health_check()
            elif 'GET /' in request_str:
                response = await self.root_response()
            else:
                response = await self.not_found_response()
            
            # Send response
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            
        except Exception as e:
            logger.warning(f"⚠️ Health server request error: {e}")
    
    async def health_check(self):
        """Detailed health check response"""
        try:
            # Get system info
            memory = psutil.virtual_memory()
            uptime = datetime.now() - self.start_time
            
            health_data = {
                "status": "healthy",
                "service": "terabox_leech_bot",
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": uptime.total_seconds(),
                "memory": {
                    "total_mb": round(memory.total / (1024 * 1024), 2),
                    "available_mb": round(memory.available / (1024 * 1024), 2),
                    "used_percent": memory.percent
                },
                "process_id": os.getpid(),
                "version": "2.0.0"
            }
            
            response_body = json.dumps(health_data, indent=2)
            
        except Exception as e:
            logger.error(f"❌ Health check error: {e}")
            health_data = {
                "status": "error", 
                "service": "terabox_leech_bot",
                "error": str(e)
            }
            response_body = json.dumps(health_data)
        
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n"
            "{}"
        ).format(len(response_body), response_body)
        
        return response
    
    async def root_response(self):
        """Root path response"""
        response_body = json.dumps({
            "message": "Terabox Leech Pro Bot API",
            "status": "running",
            "endpoints": {
                "/health": "Health check",
                "/": "This message"
            }
        }, indent=2)
        
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n"
            "{}"
        ).format(len(response_body), response_body)
        
        return response
    
    async def not_found_response(self):
        """404 response"""
        response_body = json.dumps({"error": "Not Found"})
        
        response = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n"
            "{}"
        ).format(len(response_body), response_body)
        
        return response
    
    async def start(self):
        """Start the health server"""
        server = await asyncio.start_server(
            self.handle_request, 
            '0.0.0.0', 
            self.port
        )
        
        logger.info(f"🏥 Health server listening on 0.0.0.0:{self.port}")
        
        # Run server
        async with server:
            while not self.should_exit:
                await asyncio.sleep(1)
            
            server.close()
            await server.wait_closed()

async def create_health_server(port=8000):
    """Create and start health server"""
    health_server = HealthServer(port)
    
    # Start server in background
    asyncio.create_task(health_server.start())
    
    return health_server
                         
