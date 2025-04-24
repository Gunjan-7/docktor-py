#!/usr/bin/env python3
"""
Docker Orchestration System API Server

This script starts the API server for the Docker Orchestration System.
"""

import sys
import os
import logging
from docker_orcha.api.server import start_api_server


def main():
    """Main entry point for the API server."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Docker Orchestration System API Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--state-dir', default='./container_states', help='Directory to store state in')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Start the API server
    try:
        start_api_server(
            host=args.host,
            port=args.port,
            debug=args.debug,
            state_dir=args.state_dir
        )
    except KeyboardInterrupt:
        print("Shutting down API server...")
        sys.exit(0)


if __name__ == '__main__':
    main() 