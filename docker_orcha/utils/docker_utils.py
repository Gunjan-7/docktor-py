"""
Docker utility functions for the Docker Orchestration System.
"""

import os
import subprocess
from typing import List, Dict, Tuple, Any, Optional


def run_docker_command(command: List[str], capture_output: bool = True) -> Tuple[int, str, str]:
    """
    Run a Docker command.
    
    Args:
        command: Docker command to run
        capture_output: Whether to capture output
        
    Returns:
        Tuple[int, str, str]: Return code, stdout, stderr
    """
    try:
        # Add 'docker' to the beginning of the command if not already there
        if not command[0].startswith('docker'):
            command.insert(0, 'docker')
        
        # Run the command
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            check=False
        )
        
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def get_running_containers() -> List[Dict[str, Any]]:
    """
    Get a list of running containers.
    
    Returns:
        List[Dict[str, Any]]: List of container dictionaries
    """
    returncode, stdout, stderr = run_docker_command(['ps', '--format', '{{json .}}'])
    if returncode != 0:
        return []
    
    containers = []
    for line in stdout.strip().split('\n'):
        if line:
            try:
                import json
                container = json.loads(line)
                containers.append(container)
            except json.JSONDecodeError:
                pass
    
    return containers


def get_container_status(container_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the status of a container.
    
    Args:
        container_id: Container ID
        
    Returns:
        Optional[Dict[str, Any]]: Container status dictionary, or None if not found
    """
    returncode, stdout, stderr = run_docker_command(['inspect', container_id])
    if returncode != 0:
        return None
    
    try:
        import json
        inspection = json.loads(stdout)
        if inspection and isinstance(inspection, list):
            return inspection[0]
    except json.JSONDecodeError:
        pass
    
    return None


def build_image_from_dockerfile(dockerfile_path: str, tag: str) -> Tuple[bool, str]:
    """
    Build a Docker image from a Dockerfile.
    
    Args:
        dockerfile_path: Path to the Dockerfile
        tag: Tag for the image
        
    Returns:
        Tuple[bool, str]: Success flag and output/error message
    """
    if not os.path.exists(dockerfile_path):
        return False, f"Dockerfile not found at {dockerfile_path}"
    
    build_dir = os.path.dirname(dockerfile_path)
    returncode, stdout, stderr = run_docker_command([
        'build', 
        '-t', 
        tag, 
        '-f', 
        dockerfile_path, 
        build_dir
    ])
    
    if returncode != 0:
        return False, stderr
    
    return True, stdout 