"""
Resource requirement models for Docker containers.
"""

from dataclasses import dataclass


@dataclass
class ResourceRequirements:
    """Resource requirements for a Docker container."""
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