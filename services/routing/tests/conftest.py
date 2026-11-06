"""Fixtures compartidas: un OSRM falso en localhost para probar el proveedor sin red."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append(self.path)
        body = json.dumps(self.server.responder(self.path)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # sin log por peticion
        pass


class _Server(HTTPServer):
    def handle_error(self, request, client_address):  # el cliente puede cortar por timeout
        pass


@pytest.fixture
def osrm_stub(monkeypatch):
    """start(responder) levanta un OSRM falso y apunta ROUTING_OSRM_URL a el.

    `responder(path)` devuelve el JSON de respuesta; el servidor guarda las rutas
    pedidas en `server.hits`."""
    servers = []

    def start(responder):
        server = _Server(("127.0.0.1", 0), _Handler)
        server.responder = responder
        server.hits = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        monkeypatch.setenv("ROUTING_OSRM_URL", f"http://127.0.0.1:{server.server_port}")
        return server

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()
