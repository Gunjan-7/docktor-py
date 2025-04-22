"""
Docker Orchestration System

A comprehensive Python application to manage Docker containers with advanced scheduling
and resource allocation capabilities.
"""

import os
import sys
import json
import time
import logging
import threading
import yaml
import docker
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('docker_orchestrator')

# Priority Enum
class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# Task State Enum
class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ResourceRequirements:
    cpu_shares: int = 1024  # Default CPU shares
    memory: str = "1g"      # Default memory
    memory_swap: str = "2g" # Default memory swap
    
    def __post_init__(self):
        # Convert string values to appropriate format for Docker API
        if isinstance(self.memory, str):
            # Ensure memory value has a unit
            if self.memory.isdigit():
                self.memory = f"{self.memory}m"
        
        if isinstance(self.memory_swap, str):
            # Ensure memory_swap value has a unit
            if self.memory_swap.isdigit():
                self.memory_swap = f"{self.memory_swap}m"

@dataclass
class Task:
    id: str
    name: str
    priority: Priority
    resources: ResourceRequirements
    dockerfile_path: str = None
    dockerfile_content: str = None
    compose_path: str = None
    compose_content: str = None
    container_id: str = None
    state: TaskState = TaskState.PENDING
    checkpoint_path: str = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)

class DockerManager:
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
    
    def health_check(self, container_id: str) -> Dict:
        """Check the health of a container"""
        try:
            container = self.client.containers.get(container_id)
            inspection = container.attrs
            
            health_status = "N/A"
            if 'Health' in inspection['State']:
                health_status = inspection['State']['Health']['Status']
            
            return {
                'id': container.id,
                'name': container.name,
                'status': container.status,
                'health': health_status,
                'running': inspection['State']['Running'],
                'exit_code': inspection['State']['ExitCode'],
                'started_at': inspection['State']['StartedAt'],
                'finished_at': inspection['State']['FinishedAt'],
            }
        except Exception as e:
            logger.error(f"Failed to check container health: {str(e)}")
            return {'error': str(e)}
    
    def create_task(self, name: str, priority: Priority, resources: ResourceRequirements,
                    dockerfile_content: str = None, dockerfile_path: str = None,
                    compose_content: str = None, compose_path: str = None) -> str:
        """Create a new task"""
        with self.lock:
            task_id = f"task_{int(time.time())}_{hash(name) % 1000}"
            
            # Save dockerfile if provided
            if dockerfile_content and not dockerfile_path:
                dockerfile_path = f"./dockerfiles/{task_id}/Dockerfile"
                self.create_dockerfile(dockerfile_path, dockerfile_content)
            
            # Save compose file if provided
            if compose_content and not compose_path:
                compose_path = f"./compose/{task_id}/docker-compose.yml"
                self.create_compose_file(compose_path, compose_content)
            
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
            
            self.tasks[task_id] = task
            self._save_state()
            
            # Check if we need to reschedule tasks based on new priority
            self._reschedule_if_needed(task_id)
            
            return task_id
    
    def _reschedule_if_needed(self, new_task_id: str):
        """Reschedule tasks if a higher priority task needs resources"""
        new_task = self.tasks[new_task_id]
        
        # If the new task is not high priority, no need to preempt others
        if new_task.priority not in [Priority.HIGH, Priority.CRITICAL]:
            return
        
        # Get all running tasks with lower priority
        running_tasks = [
            task for task in self.tasks.values() 
            if task.state == TaskState.RUNNING and task.priority.value < new_task.priority.value
        ]
        
        if not running_tasks:
            return
        
        # Calculate total resources used by lower priority tasks
        total_cpu = sum(task.resources.cpu_shares for task in running_tasks)
        
        # If we need to preempt tasks to free up resources
        if new_task.resources.cpu_shares > total_cpu * 0.7:  # Rule: if new task needs >70% of used resources
            logger.info(f"Preempting tasks for high priority task {new_task_id}")
            
            # Save state and stop containers for each running task
            for task in running_tasks:
                self._checkpoint_and_stop_task(task.id)
                task.state = TaskState.PAUSED
            
            self._save_state()
    
    def _checkpoint_and_stop_task(self, task_id: str) -> bool:
        """Checkpoint and stop a running task"""
        task = self.tasks.get(task_id)
        if not task or not task.container_id:
            return False
        
        try:
            # Create checkpoint directory
            checkpoint_dir = os.path.join(self.state_dir, f"checkpoint_{task_id}")
            os.makedirs(checkpoint_dir, exist_ok=True)
            
            # Checkpoint container if supported (requires experimental Docker features and appropriate configuration)
            # In a real implementation, you might use CRIU or Docker checkpointing
            # For this example, we'll just save container inspect data
            container = self.client.containers.get(task.container_id)
            
            # Save container inspection
            inspect_data = container.attrs
            with open(os.path.join(checkpoint_dir, "container_inspect.json"), 'w') as f:
                json.dump(inspect_data, f, indent=2)
            
            # Save logs
            logs = container.logs().decode('utf-8')
            with open(os.path.join(checkpoint_dir, "container_logs.txt"), 'w') as f:
                f.write(logs)
            
            # In a real implementation, you would use actual container checkpointing
            # container.commit(repository=f"checkpoint_{task_id}", tag="latest")
            
            # Stop the container
            container.stop(timeout=10)
            
            # Update task with checkpoint path
            task.checkpoint_path = checkpoint_dir
            task.state = TaskState.PAUSED
            
            return True
        except Exception as e:
            logger.error(f"Failed to checkpoint task {task_id}: {str(e)}")
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task"""
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.PAUSED:
            return False
        
        try:
            # In a real implementation, you would restore from checkpoint
            # For this example, we'll just restart the container with the same configuration
            if task.dockerfile_path:
                # Build and run from Dockerfile
                image_tag = f"task_{task_id}"
                
                # Build the docker image
                self.client.images.build(
                    path=os.path.dirname(task.dockerfile_path),
                    dockerfile=os.path.basename(task.dockerfile_path),
                    tag=image_tag
                )
                
                # Run the container
                container = self.client.containers.run(
                    image_tag,
                    detach=True,
                    name=f"task_{task.name}_{task_id}",
                    cpu_shares=task.resources.cpu_shares,
                    mem_limit=task.resources.memory,
                    memswap_limit=task.resources.memory_swap
                )
                
                task.container_id = container.id
            
            elif task.compose_path:
                # Use docker-compose to start services
                # In a real implementation, you would use the Docker Compose API
                # For this example, we'll simulate it
                compose_dir = os.path.dirname(task.compose_path)
                container_name = f"task_{task.name}_{task_id}"
                
                # Simulate docker-compose up
                # In reality, you would use docker-compose Python library or subprocess
                container = self.client.containers.run(
                    "alpine:latest",  # Placeholder, in reality would come from compose file
                    detach=True,
                    name=container_name,
                    cpu_shares=task.resources.cpu_shares,
                    mem_limit=task.resources.memory,
                    memswap_limit=task.resources.memory_swap
                )
                
                task.container_id = container.id
            
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            self._save_state()
            
            return True
        except Exception as e:
            logger.error(f"Failed to resume task {task_id}: {str(e)}")
            return False
    
    def start_task(self, task_id: str) -> bool:
        """Start a pending task"""
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.PENDING:
            return False
        
        try:
            if task.dockerfile_path:
                # Build and run from Dockerfile
                image_tag = f"task_{task_id}"
                
                # Build the docker image
                self.client.images.build(
                    path=os.path.dirname(task.dockerfile_path),
                    dockerfile=os.path.basename(task.dockerfile_path),
                    tag=image_tag
                )
                
                # Run the container
                container = self.client.containers.run(
                    image_tag,
                    detach=True,
                    name=f"task_{task.name}_{task_id}",
                    cpu_shares=task.resources.cpu_shares,
                    mem_limit=task.resources.memory,
                    memswap_limit=task.resources.memory_swap
                )
                
                task.container_id = container.id
            
            elif task.compose_path:
                # Use docker-compose to start services
                # In a real implementation, you would use the Docker Compose API
                # For this example, we'll simulate it
                compose_dir = os.path.dirname(task.compose_path)
                container_name = f"task_{task.name}_{task_id}"
                
                # Simulate docker-compose up
                # In reality, you would use docker-compose Python library or subprocess
                container = self.client.containers.run(
                    "alpine:latest",  # Placeholder, in reality would come from compose file
                    detach=True,
                    name=container_name,
                    cpu_shares=task.resources.cpu_shares,
                    mem_limit=task.resources.memory,
                    memswap_limit=task.resources.memory_swap
                )
                
                task.container_id = container.id
            
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            self._save_state()
            
            return True
        except Exception as e:
            logger.error(f"Failed to start task {task_id}: {str(e)}")
            return False
    
    def stop_task(self, task_id: str, checkpoint: bool = True) -> bool:
        """Stop a running task"""
        task = self.tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING or not task.container_id:
            return False
        
        try:
            if checkpoint:
                return self._checkpoint_and_stop_task(task_id)
            else:
                # Just stop the container without checkpointing
                container = self.client.containers.get(task.container_id)
                container.stop(timeout=10)
                task.state = TaskState.PAUSED
                self._save_state()
                return True
        except Exception as e:
            logger.error(f"Failed to stop task {task_id}: {str(e)}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task and its associated resources"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        try:
            # Stop container if running
            if task.container_id and task.state == TaskState.RUNNING:
                try:
                    container = self.client.containers.get(task.container_id)
                    container.stop(timeout=10)
                    container.remove()
                except docker.errors.NotFound:
                    pass  # Container already gone
            
            # Clean up checkpoint directory if exists
            if task.checkpoint_path and os.path.exists(task.checkpoint_path):
                try:
                    for root, dirs, files in os.walk(task.checkpoint_path, topdown=False):
                        for file in files:
                            os.remove(os.path.join(root, file))
                        for dir in dirs:
                            os.rmdir(os.path.join(root, dir))
                    os.rmdir(task.checkpoint_path)
                except Exception as e:
                    logger.warning(f"Failed to clean up checkpoint directory: {str(e)}")
            
            # Remove task from registry
            del self.tasks[task_id]
            self._save_state()
            
            return True
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {str(e)}")
            return False
    
    def update_task_resources(self, task_id: str, resources: ResourceRequirements) -> bool:
        """Update resources for a task"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        try:
            old_resources = task.resources
            task.resources = resources
            
            # If task is running, update container resources
            if task.state == TaskState.RUNNING and task.container_id:
                try:
                    container = self.client.containers.get(task.container_id)
                    
                    # In Docker API, updating resources often requires stopping and starting
                    # For now, we'll just log that this would happen
                    logger.info(f"Would update container {task.container_id} resources: "
                             f"CPU: {old_resources.cpu_shares} -> {resources.cpu_shares}, "
                             f"Memory: {old_resources.memory} -> {resources.memory}")
                    
                    # In a real implementation, you might use container.update() API
                    # or docker-compose scale to adjust resources
                    
                except docker.errors.NotFound:
                    logger.warning(f"Container {task.container_id} not found")
            
            self._save_state()
            return True
        except Exception as e:
            logger.error(f"Failed to update task resources: {str(e)}")
            return False
    
    def list_tasks(self, status_filter: Optional[TaskState] = None) -> List[Dict]:
        """List all tasks, optionally filtered by status"""
        try:
            tasks_list = []
            for task_id, task in self.tasks.items():
                if status_filter is None or task.state == status_filter:
                    tasks_list.append(task.to_dict())
            return tasks_list
        except Exception as e:
            logger.error(f"Failed to list tasks: {str(e)}")
            return []
    
    def rebalance_resources(self) -> bool:
        """Rebalance resources among running tasks based on priority"""
        with self.lock:
            try:
                # Get all running tasks
                running_tasks = [
                    task for task in self.tasks.values() 
                    if task.state == TaskState.RUNNING
                ]
                
                if not running_tasks:
                    return True  # Nothing to rebalance
                
                # Sort tasks by priority (higher priority first)
                running_tasks.sort(key=lambda t: t.priority.value, reverse=True)
                
                # Calculate total available resources (simplified)
                total_cpu = 4096  # Example: Total CPU shares
                total_memory = 8 * 1024  # Example: 8GB in MB
                
                # Simple allocation strategy: distribute proportionally based on priority
                priority_weights = {
                    Priority.LOW: 1,
                    Priority.MEDIUM: 2,
                    Priority.HIGH: 4,
                    Priority.CRITICAL: 8
                }
                
                total_weight = sum(priority_weights[task.priority] for task in running_tasks)
                
                # Allocate resources
                for task in running_tasks:
                    weight = priority_weights[task.priority] / total_weight
                    new_cpu = int(total_cpu * weight)
                    new_memory = f"{int(total_memory * weight)}m"
                    
                    # Update task resources
                    self.update_task_resources(task.id, ResourceRequirements(
                        cpu_shares=new_cpu,
                        memory=new_memory,
                        memory_swap=f"{int(total_memory * weight * 2)}m"
                    ))
                
                return True
            except Exception as e:
                logger.error(f"Failed to rebalance resources: {str(e)}")
                return False

# Create a Flask API for the Docker Orchestrator
app = Flask(__name__)
docker_manager = DockerManager()

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Get all tasks, optionally filtered by status"""
    status = request.args.get('status')
    if status:
        try:
            status = TaskState(status)
            tasks = docker_manager.list_tasks(status)
        except ValueError:
            return jsonify({'error': f"Invalid status: {status}"}), 400
    else:
        tasks = docker_manager.list_tasks()
    
    return jsonify({'tasks': tasks})

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Create a new task"""
    data = request.json
    
    try:
        # Validate required fields
        if not data.get('name') or not data.get('priority'):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Parse priority
        try:
            priority = Priority(data['priority'])
        except ValueError:
            return jsonify({'error': f"Invalid priority: {data['priority']}"}), 400
        
        # Parse resources
        resources_dict = data.get('resources', {})
        resources = ResourceRequirements(
            cpu_shares=resources_dict.get('cpu_shares', 1024),
            memory=resources_dict.get('memory', '1g'),
            memory_swap=resources_dict.get('memory_swap', '2g')
        )
        
        # Create task
        task_id = docker_manager.create_task(
            name=data['name'],
            priority=priority,
            resources=resources,
            dockerfile_content=data.get('dockerfile_content'),
            dockerfile_path=data.get('dockerfile_path'),
            compose_content=data.get('compose_content'),
            compose_path=data.get('compose_path')
        )
        
        return jsonify({'task_id': task_id, 'status': 'created'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get task details"""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(task.to_dict())

@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    """Update task resources"""
    data = request.json
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    try:
        # Update resources if provided
        if 'resources' in data:
            resources_dict = data['resources']
            resources = ResourceRequirements(
                cpu_shares=resources_dict.get('cpu_shares', task.resources.cpu_shares),
                memory=resources_dict.get('memory', task.resources.memory),
                memory_swap=resources_dict.get('memory_swap', task.resources.memory_swap)
            )
            
            success = docker_manager.update_task_resources(task_id, resources)
            if not success:
                return jsonify({'error': 'Failed to update task resources'}), 500
        
        return jsonify({'status': 'updated', 'task_id': task_id})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Delete a task"""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    success = docker_manager.delete_task(task_id)
    if success:
        return jsonify({'status': 'deleted', 'task_id': task_id})
    else:
        return jsonify({'error': 'Failed to delete task'}), 500

@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def start_task(task_id):
    """Start a task"""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    success = docker_manager.start_task(task_id)
    if success:
        return jsonify({'status': 'started', 'task_id': task_id})
    else:
        return jsonify({'error': 'Failed to start task'}), 500

@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    """Stop a task"""
    data = request.json or {}
    checkpoint = data.get('checkpoint', True)
    
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    success = docker_manager.stop_task(task_id, checkpoint=checkpoint)
    if success:
        return jsonify({'status': 'stopped', 'task_id': task_id})
    else:
        return jsonify({'error': 'Failed to stop task'}), 500

@app.route('/api/tasks/<task_id>/resume', methods=['POST'])
def resume_task(task_id):
    """Resume a paused task"""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    success = docker_manager.resume_task(task_id)
    if success:
        return jsonify({'status': 'resumed', 'task_id': task_id})
    else:
        return jsonify({'error': 'Failed to resume task'}), 500

@app.route('/api/containers', methods=['GET'])
def list_containers():
    """List all containers"""
    containers = docker_manager.list_containers()
    return jsonify({'containers': containers})

@app.route('/api/containers/<container_id>/logs', methods=['GET'])
def get_logs(container_id):
    """Get container logs"""
    tail = request.args.get('tail', 100, type=int)
    logs = docker_manager.get_container_logs(container_id, tail=tail)
    return jsonify({'logs': logs})

@app.route('/api/containers/<container_id>/health', methods=['GET'])
def health_check(container_id):
    """Check container health"""
    health = docker_manager.health_check(container_id)
    return jsonify(health)

@app.route('/api/system/rebalance', methods=['POST'])
def rebalance_resources():
    """Rebalance resources among running tasks"""
    success = docker_manager.rebalance_resources()
    if success:
        return jsonify({'status': 'rebalanced'})
    else:
        return jsonify({'error': 'Failed to rebalance resources'}), 500

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """Get overall system status"""
    try:
        # Get Docker system info
        docker_info = docker_manager.client.info()
        
        # Get counts of tasks by state
        task_counts = {}
        for state in TaskState:
            task_counts[state.value] = len([t for t in docker_manager.tasks.values() if t.state == state])
        
        # Get running containers
        containers = docker_manager.list_containers()
        
        return jsonify({
            'docker_version': docker_info.get('ServerVersion', 'Unknown'),
            'containers_running': docker_info.get('ContainersRunning', 0),
            'containers_paused': docker_info.get('ContainersPaused', 0),
            'containers_stopped': docker_info.get('ContainersStopped', 0),
            'images': docker_info.get('Images', 0),
            'task_counts': task_counts,
            'managed_containers': len(containers),
            'cpu_usage': 'N/A',  # Would require additional metrics collection
            'memory_usage': 'N/A',  # Would require additional metrics collection
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

class JobScheduler:
    """
    Job scheduler for managing task execution and resource allocation
    """
    def __init__(self, docker_manager: DockerManager):
        self.docker_manager = docker_manager
        self.running = False
        self.scheduler_thread = None
        self.lock = threading.RLock()
    
    def start(self):
        """Start the scheduler thread"""
        with self.lock:
            if self.running:
                return False
            
            self.running = True
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            return True
    
    def stop(self):
        """Stop the scheduler thread"""
        with self.lock:
            if not self.running:
                return False
            
            self.running = False
            if self.scheduler_thread:
                self.scheduler_thread.join(timeout=5)
            return True
    
    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.running:
            try:
                self._process_pending_tasks()
                self._check_running_tasks()
                self._optimize_resource_allocation()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
            
            # Sleep for a bit before next cycle
            time.sleep(5)
    
    def _process_pending_tasks(self):
        """Process pending tasks based on priority"""
        with self.docker_manager.lock:
            # Get pending tasks sorted by priority (highest first)
            pending_tasks = [
                task for task in self.docker_manager.tasks.values()
                if task.state == TaskState.PENDING
            ]
            
            if not pending_tasks:
                return
            
            pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)
            
            # Try to start highest priority tasks first
            for task in pending_tasks:
                # Check if we have enough resources (simplified check)
                if self._has_sufficient_resources(task):
                    self.docker_manager.start_task(task.id)
    
    def _has_sufficient_resources(self, task: Task) -> bool:
        """Check if there are sufficient resources to run a task"""
        # In a real implementation, this would check actual system resources
        # For this example, we'll use a simple heuristic
        
        # Get all running tasks
        running_tasks = [
            t for t in self.docker_manager.tasks.values()
            if t.state == TaskState.RUNNING
        ]
        
        # Calculate used resources (simplified)
        used_cpu = sum(t.resources.cpu_shares for t in running_tasks)
        
        # Assume total system resources (simplified)
        total_cpu = 8192  # Example value
        
        # Check if we have enough free resources
        return used_cpu + task.resources.cpu_shares <= total_cpu
    
    def _check_running_tasks(self):
        """Check status of running tasks"""
        with self.docker_manager.lock:
            running_tasks = [
                task for task in self.docker_manager.tasks.values()
                if task.state == TaskState.RUNNING and task.container_id
            ]
            
            for task in running_tasks:
                try:
                    container = self.docker_manager.client.containers.get(task.container_id)
                    
                    # Check if container has exited
                    if container.status not in ['running', 'created']:
                        # Get exit code
                        exit_code = container.attrs['State'].get('ExitCode', -1)
                        
                        if exit_code == 0:
                            # Task completed successfully
                            task.state = TaskState.COMPLETED
                            task.completed_at = time.time()
                        else:
                            # Task failed
                            task.state = TaskState.FAILED
                            logger.warning(f"Task {task.id} failed with exit code {exit_code}")
                        
                        self.docker_manager._save_state()
                
                except docker.errors.NotFound:
                    # Container no longer exists
                    logger.warning(f"Container {task.container_id} for task {task.id} not found")
                    task.container_id = None
                    task.state = TaskState.FAILED
                    self.docker_manager._save_state()
    
    def _optimize_resource_allocation(self):
        """Optimize resource allocation for running tasks"""
        with self.docker_manager.lock:
            # Get all running tasks
            running_tasks = [
                task for task in self.docker_manager.tasks.values()
                if task.state == TaskState.RUNNING
            ]
            
            if len(running_tasks) <= 1:
                return  # No need to optimize with 0 or 1 tasks
            
            # Check if any high priority task needs more resources
            high_priority_tasks = [
                task for task in running_tasks
                if task.priority in [Priority.HIGH, Priority.CRITICAL]
            ]
            
            if high_priority_tasks:
                # Reallocate resources to favor high priority tasks
                self.docker_manager.rebalance_resources()
            
            # Check for recently completed tasks to redistribute resources
            completed_tasks = [
                task for task in self.docker_manager.tasks.values()
                if task.state == TaskState.COMPLETED and task.completed_at 
                and time.time() - task.completed_at < 60  # Completed in last minute
            ]
            
            if completed_tasks:
                # Reallocate resources after task completion
                self.docker_manager.rebalance_resources()

# Create scheduler
scheduler = JobScheduler(docker_manager)

@app.route('/api/scheduler/start', methods=['POST'])
def start_scheduler():
    """Start the job scheduler"""
    success = scheduler.start()
    return jsonify({'status': 'started' if success else 'already running'})

@app.route('/api/scheduler/stop', methods=['POST'])
def stop_scheduler():
    """Stop the job scheduler"""
    success = scheduler.stop()
    return jsonify({'status': 'stopped' if success else 'not running'})

def main():
    """Main entry point"""
    # Start the scheduler
    scheduler.start()
    
    # Start the Flask API
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    main()  