"""
Task model for the Docker Orchestration System.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional

from docker_orcha.models.enums import Priority, TaskState
from docker_orcha.models.resources import ResourceRequirements


@dataclass
class Task:
    """
    Represents a task in the Docker Orchestration System.
    A task can be a Docker container created from a Dockerfile or a docker-compose.yml file.
    """
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
        """Convert task to dictionary representation."""
        return asdict(self) 