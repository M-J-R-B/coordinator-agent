"""Run the device tools over stdio: python -m mcp_server"""
from mcp_server.server import create_server

if __name__ == "__main__":
    create_server().run()
