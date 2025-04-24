"""
Docker Manager for the Docker Orchestration System.

This module provides the core functionality for managing Docker containers,
including creation, monitoring, and resource management.
"""

import os
import json
import time
import logging
import threading
import yaml
import docker
from typing import Dict, List, Optional, Union

from docker_orcha.models.enums import Priority, TaskState
from docker_orcha.models.resources import ResourceRequirements
from docker_orcha.models.task import Task


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('docker_orchestrator')


class DockerManager:
    """
    Manages Docker containers with advanced scheduling and resource allocation.
    """
    def __init__(self, state_dir: str = "./container_states"):
        # Configure Docker client for Windows with WSL2
        self.client = docker.DockerClient(base_url='npipe:////./pipe/docker_engine')
        self.state_dir = state_dir
        self.tasks = {}  # Task ID -> Task object
        self.lock = threading.RLock()
        
        # Ensure state directory exists
        os.makedirs(self.state_dir, exist_ok=True)
        
        # Load saved state if available
        self._load_state()
        
    def _load_state(self):
        """Load saved tasks state from disk"""
        state_file = os.path.join(self.state_dir, "tasks_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    tasks_data = json.load(f)
                
                for task_id, task_dict in tasks_data.items():
                    # Convert dictionary back to Task object
                    resources = ResourceRequirements(**task_dict.get('resources', {}))
                    task_dict['resources'] = resources
                    
                    # Convert string enums back to enum values
                    task_dict['priority'] = Priority(task_dict['priority'])
                    task_dict['state'] = TaskState(task_dict['state'])
                    
                    self.tasks[task_id] = Task(**task_dict)
                
                logger.info(f"Loaded state with {len(self.tasks)} tasks")
            except Exception as e:
                logger.error(f"Failed to load state: {str(e)}")
    
    def _save_state(self):
        """Save current tasks state to disk"""
        state_file = os.path.join(self.state_dir, "tasks_state.json")
        try:
            tasks_dict = {task_id: task.to_dict() for task_id, task in self.tasks.items()}
            with open(state_file, 'w') as f:
                json.dump(tasks_dict, f, indent=2)
            logger.info(f"Saved state with {len(self.tasks)} tasks")
        except Exception as e:
            logger.error(f"Failed to save state: {str(e)}")
    
    def create_dockerfile(self, path: str, content: str) -> bool:
        """Create a Dockerfile at the specified path"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to create Dockerfile: {str(e)}")
            return False
    
    def edit_dockerfile(self, path: str, content: str) -> bool:
        """Edit an existing Dockerfile"""
        if not os.path.exists(path):
            logger.error(f"Dockerfile not found at {path}")
            return False
        
        try:
            with open(path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to edit Dockerfile: {str(e)}")
            return False
    
    def delete_dockerfile(self, path: str) -> bool:
        """Delete a Dockerfile"""
        if not os.path.exists(path):
            logger.error(f"Dockerfile not found at {path}")
            return False
        
        try:
            os.remove(path)
            return True
        except Exception as e:
            logger.error(f"Failed to delete Dockerfile: {str(e)}")
            return False
    
    def create_compose_file(self, path: str, content: Union[str, Dict]) -> bool:
        """Create a docker-compose.yml file"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # If content is a dictionary, convert to YAML
            if isinstance(content, dict):
                content = yaml.dump(content)
                
            with open(path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to create compose file: {str(e)}")
            return False
    
    def edit_compose_file(self, path: str, content: Union[str, Dict]) -> bool:
        """Edit an existing docker-compose.yml file"""
        if not os.path.exists(path):
            logger.error(f"Compose file not found at {path}")
            return False
        
        try:
            # If content is a dictionary, convert to YAML
            if isinstance(content, dict):
                content = yaml.dump(content)
                
            with open(path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to edit compose file: {str(e)}")
            return False
    
    def delete_compose_file(self, path: str) -> bool:
        """Delete a docker-compose.yml file"""
        if not os.path.exists(path):
            logger.error(f"Compose file not found at {path}")
            return False
        
        try:
            os.remove(path)
            return True
        except Exception as e:
            logger.error(f"Failed to delete compose file: {str(e)}")
            return False
    
    def list_containers(self) -> List[Dict]:
        """List all containers managed by this orchestrator"""
        try:
            containers = []
            for task_id, task in self.tasks.items():
                if task.container_id:
                    try:
                        container = self.client.containers.get(task.container_id)
                        containers.append({
                            'id': container.id,
                            'name': container.name,
                            'status': container.status,
                            'task_id': task_id,
                            'task_name': task.name,
                            'priority': task.priority,
                        })
                    except docker.errors.NotFound:
                        # Container no longer exists
                        logger.warning(f"Container {task.container_id} for task {task_id} not found")
                        task.container_id = None
            
            return containers
        except Exception as e:
            logger.error(f"Failed to list containers: {str(e)}")
            return []
    
    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """Get logs from a container"""
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail).decode('utf-8')
            return logs
        except Exception as e:
            logger.error(f"Failed to get container logs: {str(e)}")
            return f"Error retrieving logs: {str(e)}"
    
    def create_task(self, name: str, priority: Priority, resources: ResourceRequirements,
                 dockerfile_content: str = None, dockerfile_path: str = None,
                 compose_content: str = None, compose_path: str = None) -> str:
        """
        Create a new task.
        
        Returns:
            str: The ID of the created task
        """
        from uuid import uuid4
        
        task_id = str(uuid4())
        task = Task(
            id=task_id,
            name=name,
            priority=priority,
            resources=resources,
            dockerfile_path=dockerfile_path,
            dockerfile_content=dockerfile_content,
            compose_path=compose_path,
            compose_content=compose_content
        )
        
        with self.lock:
            self.tasks[task_id] = task
            self._save_state()
            
            # If priority is high or critical, reschedule to accommodate
            if priority in [Priority.HIGH, Priority.CRITICAL]:
                self._reschedule_if_needed(task_id)
        
        return task_id
    
    def _reschedule_if_needed(self, new_task_id: str):
        """
        Reschedule tasks if needed to accommodate a high priority task.
        
        Args:
            new_task_id: The ID of the new high-priority task
        """
        new_task = self.tasks[new_task_id]
        
        # If there are no resources available, pause lower priority tasks
        available_resources = self._get_available_resources()
        required_resources = self._calculate_required_resources(new_task)
        
        if not self._has_sufficient_resources(available_resources, required_resources):
            # Find candidate tasks to pause
            candidate_tasks = []
            for task_id, task in self.tasks.items():
                if task.state == TaskState.RUNNING and task.priority.value < new_task.priority.value:
                    candidate_tasks.append((task_id, task))
            
            # Sort by priority (lowest first)
            candidate_tasks.sort(key=lambda x: x[1].priority.value)
            
            # Pause tasks until we have enough resources
            for task_id, _ in candidate_tasks:
                self._checkpoint_and_stop_task(task_id)
                
                # Check if we now have enough resources
                available_resources = self._get_available_resources()
                if self._has_sufficient_resources(available_resources, required_resources):
                    break
    
    def _checkpoint_and_stop_task(self, task_id: str) -> bool:
        """
        Checkpoint and stop a running task.
        
        Args:
            task_id: The ID of the task to checkpoint and stop
            
        Returns:
            bool: True if successful, False otherwise
        """
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING:
            return False
        
        try:
            container = self.client.containers.get(task.container_id)
            
            # Create checkpoint directory if it doesn't exist
            checkpoint_dir = os.path.join(self.state_dir, "checkpoints", task_id)
            os.makedirs(checkpoint_dir, exist_ok=True)
            
            # Generate checkpoint
            container.pause()
            
            # Update task state
            task.state = TaskState.PAUSED
            task.checkpoint_path = checkpoint_dir
            
            # Stop container
            container.stop(timeout=10)
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to checkpoint and stop task {task_id}: {str(e)}")
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """
        Resume a paused task.
        
        Args:
            task_id: The ID of the task to resume
            
        Returns:
            bool: True if successful, False otherwise
        """
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.PAUSED:
            return False
        
        try:
            # Check if we have enough resources to resume
            available_resources = self._get_available_resources()
            required_resources = self._calculate_required_resources(task)
            
            if not self._has_sufficient_resources(available_resources, required_resources):
                logger.warning(f"Not enough resources to resume task {task_id}")
                return False
            
            # Create a new container
            container_config = {
                "image": self._get_task_image(task),
                "name": f"task_{task_id}",
                "detach": True,
                "cpu_shares": task.resources.cpu_shares,
                "mem_limit": task.resources.memory,
                "memswap_limit": task.resources.memory_swap,
            }
            
            container = self.client.containers.run(**container_config)
            task.container_id = container.id
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            
            # Restore from checkpoint if available
            if task.checkpoint_path and os.path.exists(task.checkpoint_path):
                # Restore checkpoint (implementation depends on Docker version)
                pass
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to resume task {task_id}: {str(e)}")
            return False
    
    def _get_task_image(self, task: Task) -> str:
        """
        Get the Docker image for a task.
        
        Args:
            task: The task
            
        Returns:
            str: The Docker image name
        """
        # This is a simplification - in a real implementation you would build
        # the image from the Dockerfile or extract it from the docker-compose.yml
        if task.dockerfile_path:
            # Build from Dockerfile
            with open(task.dockerfile_path, 'r') as f:
                content = f.read()
                # Extract base image
                for line in content.split('\n'):
                    if line.strip().startswith('FROM '):
                        return line.strip().split(' ')[1]
        
        # Default to a base image
        return "alpine:latest"
    
    def start_task(self, task_id: str) -> bool:
        """
        Start a task.
        
        Args:
            task_id: The ID of the task to start
            
        Returns:
            bool: True if successful, False otherwise
        """
        task = self.tasks.get(task_id)
        if not task or task.state not in [TaskState.PENDING, TaskState.PAUSED]:
            return False
        
        try:
            # Check if we have enough resources to start
            available_resources = self._get_available_resources()
            required_resources = self._calculate_required_resources(task)
            
            if not self._has_sufficient_resources(available_resources, required_resources):
                logger.warning(f"Not enough resources to start task {task_id}")
                return False
            
            # If it's a Dockerfile task, build the image
            image_name = None
            if task.dockerfile_path:
                build_path = os.path.dirname(task.dockerfile_path)
                image_name = f"task_{task_id}"
                self.client.images.build(path=build_path, tag=image_name, quiet=False)
            elif task.dockerfile_content:
                # Create temporary Dockerfile
                temp_dir = os.path.join(self.state_dir, "dockerfiles", task_id)
                os.makedirs(temp_dir, exist_ok=True)
                
                with open(os.path.join(temp_dir, "Dockerfile"), 'w') as f:
                    f.write(task.dockerfile_content)
                
                image_name = f"task_{task_id}"
                self.client.images.build(path=temp_dir, tag=image_name, quiet=False)
            
            # If it's a docker-compose task, use docker-compose
            if task.compose_path or task.compose_content:
                # This would involve using docker-compose, which is more complex
                # and is not implemented in this example
                pass
            
            # Create and start the container
            container_config = {
                "image": image_name or self._get_task_image(task),
                "name": f"task_{task_id}",
                "detach": True,
                "cpu_shares": task.resources.cpu_shares,
                "mem_limit": task.resources.memory,
                "memswap_limit": task.resources.memory_swap,
            }
            
            container = self.client.containers.run(**container_config)
            task.container_id = container.id
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to start task {task_id}: {str(e)}")
            task.state = TaskState.FAILED
            self._save_state()
            return False
    
    def stop_task(self, task_id: str, checkpoint: bool = True) -> bool:
        """
        Stop a running task.
        
        Args:
            task_id: The ID of the task to stop
            checkpoint: Whether to create a checkpoint before stopping
            
        Returns:
            bool: True if successful, False otherwise
        """
        if checkpoint:
            return self._checkpoint_and_stop_task(task_id)
        
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING:
            return False
        
        try:
            container = self.client.containers.get(task.container_id)
            container.stop(timeout=10)
            
            task.state = TaskState.PAUSED
            task.completed_at = time.time()
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to stop task {task_id}: {str(e)}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.
        
        Args:
            task_id: The ID of the task to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        try:
            # Stop the container if it's running
            if task.state == TaskState.RUNNING and task.container_id:
                try:
                    container = self.client.containers.get(task.container_id)
                    container.stop(timeout=5)
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
            
            # Remove the task from the state
            with self.lock:
                del self.tasks[task_id]
                self._save_state()
            
            # Clean up any resources
            if task.checkpoint_path and os.path.exists(task.checkpoint_path):
                import shutil
                shutil.rmtree(task.checkpoint_path)
            
            return True
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {str(e)}")
            return False
    
    def update_task_resources(self, task_id: str, resources: ResourceRequirements) -> bool:
        """
        Update the resource requirements of a task.
        
        Args:
            task_id: The ID of the task to update
            resources: The new resource requirements
            
        Returns:
            bool: True if successful, False otherwise
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        old_resources = task.resources
        task.resources = resources
        
        # If the task is running, update the container resources
        if task.state == TaskState.RUNNING and task.container_id:
            try:
                container = self.client.containers.get(task.container_id)
                container.update(
                    cpu_shares=resources.cpu_shares,
                    mem_limit=resources.memory,
                    memswap_limit=resources.memory_swap
                )
            except Exception as e:
                logger.error(f"Failed to update container resources: {str(e)}")
                task.resources = old_resources
                return False
        
        self._save_state()
        return True
    
    def list_tasks(self, status_filter: Optional[TaskState] = None) -> List[Dict]:
        """
        List all tasks, optionally filtered by status.
        
        Args:
            status_filter: Optional status to filter by
            
        Returns:
            List[Dict]: List of task dictionaries
        """
        result = []
        for task in self.tasks.values():
            if status_filter is None or task.state == status_filter:
                result.append(task.to_dict())
        return result
    
    def rebalance_resources(self) -> bool:
        """
        Rebalance resources based on task priorities.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get all running tasks
            running_tasks = [(task_id, task) for task_id, task in self.tasks.items() 
                            if task.state == TaskState.RUNNING]
            
            # Sort by priority (highest first)
            running_tasks.sort(key=lambda x: x[1].priority.value, reverse=True)
            
            # Calculate total resources
            available_resources = self._get_system_resources()
            
            # Allocate resources based on priority
            total_tasks = len(running_tasks)
            if total_tasks == 0:
                return True
            
            # Simple allocation strategy: higher priority gets more resources
            for i, (task_id, task) in enumerate(running_tasks):
                priority_weight = (4 - i % 4) / 10  # Simple weighting based on priority
                
                # Adjust container resources
                if task.container_id:
                    try:
                        container = self.client.containers.get(task.container_id)
                        
                        # Calculate new resource limits
                        cpu_shares = int(1024 * priority_weight)
                        memory = f"{int(available_resources['memory'] * priority_weight)}m"
                        memory_swap = f"{int(available_resources['memory_swap'] * priority_weight)}m"
                        
                        # Update container
                        container.update(
                            cpu_shares=cpu_shares,
                            mem_limit=memory,
                            memswap_limit=memory_swap
                        )
                        
                        # Update task resources
                        task.resources = ResourceRequirements(
                            cpu_shares=cpu_shares,
                            memory=memory,
                            memory_swap=memory_swap
                        )
                    except Exception as e:
                        logger.error(f"Failed to update container {task.container_id}: {str(e)}")
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to rebalance resources: {str(e)}")
            return False
    
    def _get_available_resources(self) -> Dict:
        """
        Get available system resources.
        
        Returns:
            Dict: Available resources
        """
        # This is a simplification - in a real implementation you would
        # get the actual available resources from the system
        return {
            "cpu": 4,  # Number of CPU cores
            "memory": 8 * 1024 * 1024 * 1024,  # 8 GB in bytes
            "memory_swap": 16 * 1024 * 1024 * 1024,  # 16 GB in bytes
        }
    
    def _get_system_resources(self) -> Dict:
        """
        Get total system resources.
        
        Returns:
            Dict: Total system resources
        """
        # This is a simplification - in a real implementation you would
        # get the actual system resources
        return {
            "cpu": 8,  # Number of CPU cores
            "memory": 16 * 1024 * 1024 * 1024,  # 16 GB in bytes
            "memory_swap": 32 * 1024 * 1024 * 1024,  # 32 GB in bytes
        }
    
    def _calculate_required_resources(self, task: Task) -> Dict:
        """
        Calculate resources required by a task.
        
        Args:
            task: The task
            
        Returns:
            Dict: Required resources
        """
        # Convert memory string to bytes
        memory_bytes = self._parse_memory_string(task.resources.memory)
        memory_swap_bytes = self._parse_memory_string(task.resources.memory_swap)
        
        return {
            "cpu": task.resources.cpu_shares / 1024,  # Approximate CPU cores
            "memory": memory_bytes,
            "memory_swap": memory_swap_bytes,
        }
    
    def _parse_memory_string(self, memory_str: str) -> int:
        """
        Parse a memory string (e.g., "1g", "512m") to bytes.
        
        Args:
            memory_str: The memory string
            
        Returns:
            int: Memory in bytes
        """
        if not memory_str:
            return 0
        
        memory_str = memory_str.lower()
        if memory_str.endswith('k'):
            return int(memory_str[:-1]) * 1024
        elif memory_str.endswith('m'):
            return int(memory_str[:-1]) * 1024 * 1024
        elif memory_str.endswith('g'):
            return int(memory_str[:-1]) * 1024 * 1024 * 1024
        else:
            try:
                return int(memory_str)
            except ValueError:
                return 0
    
    def _has_sufficient_resources(self, available: Dict, required: Dict) -> bool:
        """
        Check if there are sufficient resources to satisfy requirements.
        
        Args:
            available: Available resources
            required: Required resources
            
        Returns:
            bool: True if sufficient resources are available
        """
        return (available["cpu"] >= required["cpu"] and
                available["memory"] >= required["memory"] and
                available["memory_swap"] >= required["memory_swap"]) 