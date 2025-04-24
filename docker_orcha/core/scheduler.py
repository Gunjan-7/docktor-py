"""
Job scheduler for the Docker Orchestration System.

This module provides the scheduling functionality to automatically start and manage
Docker containers based on their priority and resource requirements.
"""

import time
import logging
import threading
from typing import Dict, List, Any

from docker_orcha.models.enums import TaskState, Priority
from docker_orcha.models.task import Task
from docker_orcha.core.docker_manager import DockerManager


logger = logging.getLogger('docker_orchestrator.scheduler')


class JobScheduler:
    """
    Manages scheduling of Docker container tasks based on priority and resources.
    """
    def __init__(self, docker_manager: DockerManager):
        """
        Initialize the job scheduler.
        
        Args:
            docker_manager: The Docker manager instance
        """
        self.docker_manager = docker_manager
        self.running = False
        self.thread = None
        self.check_interval = 5  # seconds
    
    def start(self):
        """Start the scheduler."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()
        logger.info("Scheduler started")
        return True
    
    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
            self.thread = None
        
        logger.info("Scheduler stopped")
        return True
    
    def _scheduler_loop(self):
        """Main scheduler loop."""
        while self.running:
            try:
                # Process pending tasks
                self._process_pending_tasks()
                
                # Check running tasks
                self._check_running_tasks()
                
                # Optimize resource allocation
                self._optimize_resource_allocation()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
            
            # Sleep for the check interval
            time.sleep(self.check_interval)
    
    def _process_pending_tasks(self):
        """Process pending tasks."""
        # Get all pending tasks
        pending_tasks = []
        for task_id, task in self.docker_manager.tasks.items():
            if task.state == TaskState.PENDING:
                pending_tasks.append((task_id, task))
        
        # Sort by priority (highest first) and creation time (oldest first)
        pending_tasks.sort(key=lambda x: (
            -x[1].priority.value,  # Negative because we want highest priority first
            x[1].created_at
        ))
        
        # Try to start each task
        for task_id, _ in pending_tasks:
            # Check if we have sufficient resources
            if self._has_sufficient_resources(task_id):
                self.docker_manager.start_task(task_id)
    
    def _has_sufficient_resources(self, task_id: str) -> bool:
        """
        Check if there are sufficient resources to start a task.
        
        Args:
            task_id: The ID of the task to check
            
        Returns:
            bool: True if there are sufficient resources
        """
        task = self.docker_manager.tasks.get(task_id)
        if not task:
            return False
        
        # Get available resources
        available_resources = self.docker_manager._get_available_resources()
        
        # Calculate required resources
        required_resources = self.docker_manager._calculate_required_resources(task)
        
        # Check if there are sufficient resources
        return self.docker_manager._has_sufficient_resources(available_resources, required_resources)
    
    def _check_running_tasks(self):
        """Check the status of running tasks."""
        for task_id, task in list(self.docker_manager.tasks.items()):
            if task.state == TaskState.RUNNING and task.container_id:
                try:
                    # Get container status
                    container = self.docker_manager.client.containers.get(task.container_id)
                    status = container.status
                    
                    # If the container has exited, update the task state
                    if status == 'exited':
                        exit_code = container.attrs.get('State', {}).get('ExitCode', -1)
                        if exit_code == 0:
                            task.state = TaskState.COMPLETED
                        else:
                            task.state = TaskState.FAILED
                        
                        task.completed_at = time.time()
                        self.docker_manager._save_state()
                except Exception as e:
                    logger.error(f"Error checking container {task.container_id}: {str(e)}")
                    # If the container no longer exists, mark the task as failed
                    task.state = TaskState.FAILED
                    task.completed_at = time.time()
                    self.docker_manager._save_state()
    
    def _optimize_resource_allocation(self):
        """Optimize resource allocation based on task priorities."""
        # Only run optimization every 5 minutes
        if int(time.time()) % 300 < self.check_interval:
            # Get all running tasks
            running_tasks = [(task_id, task) for task_id, task in self.docker_manager.tasks.items() 
                           if task.state == TaskState.RUNNING]
            
            # If there are no running tasks, nothing to optimize
            if not running_tasks:
                return
            
            # Check if rebalancing is needed
            need_rebalancing = False
            
            # Check for critical tasks that might need more resources
            critical_tasks = [t for _, t in running_tasks if t.priority == Priority.CRITICAL]
            if critical_tasks:
                need_rebalancing = True
            
            # Check for high priority tasks that might need more resources
            high_priority_tasks = [t for _, t in running_tasks if t.priority == Priority.HIGH]
            if high_priority_tasks and len(running_tasks) > len(high_priority_tasks):
                need_rebalancing = True
            
            # If rebalancing is needed, do it
            if need_rebalancing:
                self.docker_manager.rebalance_resources() 