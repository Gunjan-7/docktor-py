"""
API server for the Docker Orchestration System.

This module provides the main entry point for starting the API server.
"""

import os
import logging
from docker_orcha.api.routes import app, initialize


def start_api_server(host: str = '0.0.0.0', port: int = 5000, debug: bool = False, state_dir: str = None):
    """
    Start the API server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Whether to enable debug mode
        state_dir: Directory to store state in
    """
    # Configure the state directory
    if state_dir is None:
        state_dir = os.environ.get('DOCKER_ORCHESTRATOR_STATE_DIR', './container_states')
    
    # Initialize the API
    initialize(state_dir=state_dir)
    
    # Start the Flask app
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    start_api_server(debug=True) 