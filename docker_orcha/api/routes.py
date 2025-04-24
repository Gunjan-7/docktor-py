"""
API routes for the Docker Orchestration System.

This module provides the REST API endpoints for managing Docker containers and tasks.
"""

from flask import Flask, request, jsonify
from typing import Dict, Any, Optional

from docker_orcha.models.enums import TaskState, Priority
from docker_orcha.models.resources import ResourceRequirements
from docker_orcha.core.docker_manager import DockerManager
from docker_orcha.core.scheduler import JobScheduler


app = Flask(__name__)

# Global instances
docker_manager = None
job_scheduler = None


def initialize(state_dir: str = "./container_states"):
    """Initialize the API with Docker manager and job scheduler."""
    global docker_manager, job_scheduler
    
    docker_manager = DockerManager(state_dir=state_dir)
    job_scheduler = JobScheduler(docker_manager=docker_manager)
    

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Get list of tasks, optionally filtered by status."""
    status_filter = request.args.get('status')
    
    # Convert string status to TaskState enum if provided
    task_state_filter = None
    if status_filter:
        try:
            task_state_filter = TaskState(status_filter)
        except ValueError:
            return jsonify({'error': f"Invalid status: {status_filter}"}), 400
    
    tasks = docker_manager.list_tasks(status_filter=task_state_filter)
    return jsonify(tasks)


@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Create a new task."""
    data = request.json
    
    # Validate required fields
    required_fields = ['name', 'priority']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f"Missing required field: {field}"}), 400
    
    # Convert priority string to enum
    try:
        priority = Priority(data['priority'])
    except ValueError:
        return jsonify({'error': f"Invalid priority: {data['priority']}"}), 400
    
    # Parse resource requirements
    resources_data = data.get('resources', {})
    resources = ResourceRequirements(
        cpu_shares=resources_data.get('cpu_shares', 1024),
        memory=resources_data.get('memory', '1g'),
        memory_swap=resources_data.get('memory_swap', '2g')
    )
    
    # Create the task
    task_id = docker_manager.create_task(
        name=data['name'],
        priority=priority,
        resources=resources,
        dockerfile_content=data.get('dockerfile_content'),
        dockerfile_path=data.get('dockerfile_path'),
        compose_content=data.get('compose_content'),
        compose_path=data.get('compose_path')
    )
    
    return jsonify({'task_id': task_id})


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get task details by ID."""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(task.to_dict())


@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    """Update task resources."""
    data = request.json
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    # Update resources if provided
    if 'resources' in data:
        resources_data = data['resources']
        resources = ResourceRequirements(
            cpu_shares=resources_data.get('cpu_shares', task.resources.cpu_shares),
            memory=resources_data.get('memory', task.resources.memory),
            memory_swap=resources_data.get('memory_swap', task.resources.memory_swap)
        )
        
        result = docker_manager.update_task_resources(task_id, resources)
        if not result:
            return jsonify({'error': 'Failed to update resources'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Delete a task."""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    result = docker_manager.delete_task(task_id)
    if not result:
        return jsonify({'error': 'Failed to delete task'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def start_task(task_id):
    """Start a task."""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    result = docker_manager.start_task(task_id)
    if not result:
        return jsonify({'error': 'Failed to start task'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    """Stop a task."""
    data = request.json or {}
    checkpoint = data.get('checkpoint', True)
    
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    result = docker_manager.stop_task(task_id, checkpoint=checkpoint)
    if not result:
        return jsonify({'error': 'Failed to stop task'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/tasks/<task_id>/resume', methods=['POST'])
def resume_task(task_id):
    """Resume a paused task."""
    task = docker_manager.tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    result = docker_manager.resume_task(task_id)
    if not result:
        return jsonify({'error': 'Failed to resume task'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/containers', methods=['GET'])
def list_containers():
    """List all containers."""
    containers = docker_manager.list_containers()
    return jsonify(containers)


@app.route('/api/containers/<container_id>/logs', methods=['GET'])
def get_logs(container_id):
    """Get container logs."""
    tail = request.args.get('tail', 100, type=int)
    logs = docker_manager.get_container_logs(container_id, tail=tail)
    return jsonify({'logs': logs})


@app.route('/api/containers/<container_id>/health', methods=['GET'])
def health_check(container_id):
    """Check container health."""
    # Implementation of container health check would go here
    return jsonify({'health': 'healthy'})


@app.route('/api/system/rebalance', methods=['POST'])
def rebalance_resources():
    """Rebalance system resources."""
    result = docker_manager.rebalance_resources()
    if not result:
        return jsonify({'error': 'Failed to rebalance resources'}), 500
    
    return jsonify({'result': 'success'})


@app.route('/api/system/status', methods=['GET'])
def system_status():
    """Get system status."""
    # Calculate total running, pending, etc.
    running = len([t for t in docker_manager.tasks.values() if t.state == TaskState.RUNNING])
    pending = len([t for t in docker_manager.tasks.values() if t.state == TaskState.PENDING])
    paused = len([t for t in docker_manager.tasks.values() if t.state == TaskState.PAUSED])
    completed = len([t for t in docker_manager.tasks.values() if t.state == TaskState.COMPLETED])
    failed = len([t for t in docker_manager.tasks.values() if t.state == TaskState.FAILED])
    
    # Get available resources
    available_resources = docker_manager._get_available_resources()
    
    return jsonify({
        'tasks': {
            'total': len(docker_manager.tasks),
            'running': running,
            'pending': pending,
            'paused': paused, 
            'completed': completed,
            'failed': failed
        },
        'resources': {
            'cpu': available_resources['cpu'],
            'memory': available_resources['memory'],
            'memory_swap': available_resources['memory_swap']
        },
        'scheduler_running': job_scheduler.running if job_scheduler else False
    })


@app.route('/api/scheduler/start', methods=['POST'])
def start_scheduler():
    """Start the scheduler."""
    result = job_scheduler.start()
    return jsonify({'result': 'success' if result else 'already running'})


@app.route('/api/scheduler/stop', methods=['POST'])
def stop_scheduler():
    """Stop the scheduler."""
    result = job_scheduler.stop()
    return jsonify({'result': 'success' if result else 'already stopped'}) 