# scripts/health.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import os

HOST = os.getenv("HEALTH_HOST", "0.0.0.0")
PORT = int(os.getenv("HEALTH_PORT", "8080"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
