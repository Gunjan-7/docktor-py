"""
Interactive CLI for the Docker Orchestration System.

This module provides an interactive command-line interface for managing Docker containers and tasks.
"""

import os
import sys
import time
from typing import Dict, List, Any, Optional, Callable

from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich import box
from rich.live import Live

import questionary
from questionary import Style

from docker_orcha.cli.commands import api_request, format_task_state
from docker_orcha.models.enums import Priority, TaskState
from docker_orcha.utils.formatting import format_time, bytes_to_human

# Initialize console
console = Console()

# Custom styles
custom_style = Style([
    ('qmark', 'fg:cyan bold'),
    ('question', 'bold'),
    ('answer', 'fg:green bold'),
    ('pointer', 'fg:cyan bold'),
    ('highlighted', 'fg:cyan bold'),
    ('selected', 'fg:green bold'),
    ('separator', 'fg:cyan'),
    ('instruction', 'fg:gray'),
    ('text', ''),
    ('disabled', 'fg:gray italic'),
])

# Theme configuration
THEME = {
    "app_title": "Docker Orchestrator",
    "title_color": "cyan bold",
    "border_style": "cyan",
    "border": box.ROUNDED,
    "success_color": "green bold",
    "error_color": "red bold",
    "warning_color": "yellow bold",
    "info_color": "blue bold",
    "highlight_color": "magenta",
    "task_state_colors": {
        "pending": "yellow",
        "running": "green",
        "paused": "cyan",
        "completed": "blue",
        "failed": "red"
    }
}


class NavigationStack:
    """Simple navigation stack for interactive UI."""
    
    def __init__(self):
        self.screens = []
        self.data = {}
    
    def save_step(self, step_id, data=None):
        """Save current step data."""
        self.data[step_id] = data
    
    def go_back(self):
        """Go back to previous screen."""
        if len(self.screens) > 1:
            self.screens.pop()
            return self.screens[-1]
        return None
    
    def clear(self):
        """Clear navigation stack."""
        self.screens = []
        self.data = {}
    
    def push(self, screen_id, data=None):
        """Push a new screen onto the stack."""
        self.screens.append(screen_id)
        if data:
            self.data[screen_id] = data
    
    def back(self):
        """Go back to previous screen."""
        return self.go_back()
    
    def can_go_back(self):
        """Check if we can go back."""
        return len(self.screens) > 1


def display_header():
    """Display the application header."""
    console.print(f"[{THEME['title_color']}]{THEME['app_title']}[/{THEME['title_color']}]", justify="center")
    console.print("=" * console.width, style=THEME["border_style"])


def display_footer():
    """Display the application footer."""
    console.print("=" * console.width, style=THEME["border_style"])
    console.print("Press Ctrl+C to exit", justify="center", style="dim")


def container_submenu():
    """Container management submenu."""
    while True:
        display_header()
        console.print("[bold]Container Management[/bold]", justify="center")
        
        choice = questionary.select(
            "Select an option:",
            choices=[
                "List Containers",
                "View Logs",
                "Stop Container",
                "Restart Container",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if choice == "List Containers":
            display_container_table()
        elif choice == "View Logs":
            view_container_logs()
        elif choice == "Stop Container":
            stop_container()
        elif choice == "Restart Container":
            restart_container()
        elif choice == "Back to Main Menu" or choice is None:
            return
        
        # Wait for user input before returning to menu
        if choice is not None and choice != "Back to Main Menu":
            console.print("\nPress Enter to continue...", style="dim")
            input()


def display_container_table():
    """Display a table of containers."""
    containers = api_request("containers")
    if not containers:
        console.print("[yellow]No containers found[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Task ID")
    table.add_column("Task Name")
    table.add_column("Priority")
    
    for container in containers:
        table.add_row(
            container.get('id', '')[:12],
            container.get('name', ''),
            container.get('status', ''),
            container.get('task_id', '')[:8] if container.get('task_id') else '',
            container.get('task_name', ''),
            container.get('priority', '')
        )
    
    console.print("\n[bold cyan]Containers[/bold cyan]")
    console.print(table)


def select_container() -> Optional[str]:
    """Select a container from the list."""
    containers = api_request("containers")
    if not containers:
        console.print("[yellow]No containers found[/yellow]")
        return None
    
    choices = [
        f"{c.get('name', 'unnamed')} ({c.get('id', '')[:12]}) - {c.get('status', 'unknown')}"
        for c in containers
    ]
    choices.append("Cancel")
    
    choice = questionary.select(
        "Select a container:",
        choices=choices,
        style=custom_style
    ).ask()
    
    if choice == "Cancel" or choice is None:
        return None
    
    # Extract container ID from selection
    selected_index = choices.index(choice)
    if selected_index < len(containers):
        return containers[selected_index].get('id', '')
    
    return None


def view_container_logs():
    """View container logs."""
    container_id = select_container()
    if not container_id:
        return
    
    tail = questionary.text(
        "Number of lines to show:",
        default="100",
        validate=lambda text: text.isdigit(),
        style=custom_style
    ).ask()
    
    if tail is None:
        return
    
    logs = api_request(f"containers/{container_id}/logs?tail={tail}")
    if not logs:
        return
    
    console.print(f"\n[bold cyan]Logs for container {container_id[:12]}[/bold cyan]")
    console.print(Panel(logs.get('logs', 'No logs available'), expand=False))
    
    # Option to follow logs
    follow = questionary.confirm(
        "Follow logs?",
        default=False,
        style=custom_style
    ).ask()
    
    if follow:
        console.print("[yellow]Following logs. Press Ctrl+C to stop.[/yellow]")
        try:
            last_line_count = len(logs.get('logs', '').split('\n'))
            with Live("", refresh_per_second=4) as live:
                while True:
                    time.sleep(1)
                    new_logs = api_request(f"containers/{container_id}/logs?tail={tail}")
                    
                    if new_logs:
                        live.update(Panel(new_logs.get('logs', 'No logs available'), expand=False))
        except KeyboardInterrupt:
            console.print("[yellow]Stopped following logs[/yellow]")


def stop_container():
    """Stop a container."""
    container_id = select_container()
    if not container_id:
        return
    
    # Find the task ID for this container
    containers = api_request("containers")
    task_id = None
    for container in containers:
        if container.get('id', '') == container_id:
            task_id = container.get('task_id')
            break
    
    if not task_id:
        console.print("[yellow]Could not find task ID for this container[/yellow]")
        return
    
    checkpoint = questionary.confirm(
        "Create checkpoint before stopping?",
        default=True,
        style=custom_style
    ).ask()
    
    if checkpoint is None:
        return
    
    result = api_request(f"tasks/{task_id}/stop", method="POST", data={"checkpoint": checkpoint})
    
    if result:
        console.print(f"[{THEME['success_color']}]Container stopped successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to stop container[/{THEME['error_color']}]")


def restart_container():
    """Restart a container."""
    container_id = select_container()
    if not container_id:
        return
    
    # Find the task ID for this container
    containers = api_request("containers")
    task_id = None
    for container in containers:
        if container.get('id', '') == container_id:
            task_id = container.get('task_id')
            break
    
    if not task_id:
        console.print("[yellow]Could not find task ID for this container[/yellow]")
        return
    
    # First stop the task
    stop_result = api_request(f"tasks/{task_id}/stop", method="POST")
    if not stop_result:
        console.print(f"[{THEME['error_color']}]Failed to stop container[/{THEME['error_color']}]")
        return
    
    # Then start it again
    start_result = api_request(f"tasks/{task_id}/start", method="POST")
    if start_result:
        console.print(f"[{THEME['success_color']}]Container restarted successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to restart container[/{THEME['error_color']}]")


def task_submenu():
    """Task management submenu."""
    while True:
        display_header()
        console.print("[bold]Task Management[/bold]", justify="center")
        
        choice = questionary.select(
            "Select an option:",
            choices=[
                "List Tasks",
                "Create Task",
                "Start Task",
                "Stop Task",
                "Resume Task",
                "Delete Task",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if choice == "List Tasks":
            display_task_table()
        elif choice == "Create Task":
            create_task()
        elif choice == "Start Task":
            start_task()
        elif choice == "Stop Task":
            stop_task()
        elif choice == "Resume Task":
            resume_task()
        elif choice == "Delete Task":
            delete_task()
        elif choice == "Back to Main Menu" or choice is None:
            return
        
        # Wait for user input before returning to menu
        if choice is not None and choice != "Back to Main Menu":
            console.print("\nPress Enter to continue...", style="dim")
            input()


def display_task_table():
    """Display a table of tasks."""
    status_filter = questionary.select(
        "Filter by status:",
        choices=[
            "All",
            "Pending",
            "Running",
            "Paused",
            "Completed",
            "Failed"
        ],
        style=custom_style
    ).ask()
    
    if status_filter is None:
        return
    
    url = "tasks"
    if status_filter != "All":
        url += f"?status={status_filter.lower()}"
    
    tasks = api_request(url)
    if not tasks:
        console.print("[yellow]No tasks found[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("Priority")
    table.add_column("CPU")
    table.add_column("Memory")
    table.add_column("Created")
    table.add_column("Started")
    
    for task in tasks:
        table.add_row(
            task.get('id', '')[:8],
            task.get('name', ''),
            format_task_state(task.get('state', '')),
            task.get('priority', ''),
            str(task.get('resources', {}).get('cpu_shares', '')),
            task.get('resources', {}).get('memory', ''),
            format_time(task.get('created_at')),
            format_time(task.get('started_at'))
        )
    
    console.print("\n[bold cyan]Tasks[/bold cyan]")
    console.print(table)


def select_task() -> Optional[str]:
    """Select a task from the list."""
    tasks = api_request("tasks")
    if not tasks:
        console.print("[yellow]No tasks found[/yellow]")
        return None
    
    choices = [
        f"{t.get('name', 'unnamed')} ({t.get('id', '')[:8]}) - {t.get('state', 'unknown')}"
        for t in tasks
    ]
    choices.append("Cancel")
    
    choice = questionary.select(
        "Select a task:",
        choices=choices,
        style=custom_style
    ).ask()
    
    if choice == "Cancel" or choice is None:
        return None
    
    # Extract task ID from selection
    selected_index = choices.index(choice)
    if selected_index < len(tasks):
        return tasks[selected_index].get('id', '')
    
    return None


def create_task():
    """Create a new task."""
    # Get task name
    name = questionary.text(
        "Task name:",
        validate=lambda text: len(text) > 0,
        style=custom_style
    ).ask()
    
    if name is None:
        return
    
    # Get task priority
    priority = questionary.select(
        "Task priority:",
        choices=[
            "Low",
            "Medium",
            "High",
            "Critical"
        ],
        style=custom_style
    ).ask()
    
    if priority is None:
        return
    
    # Get resource requirements
    cpu_shares = questionary.text(
        "CPU shares (default: 1024):",
        default="1024",
        validate=lambda text: text.isdigit(),
        style=custom_style
    ).ask()
    
    if cpu_shares is None:
        return
    
    memory = questionary.text(
        "Memory (e.g., 1g, 512m):",
        default="1g",
        style=custom_style
    ).ask()
    
    if memory is None:
        return
    
    memory_swap = questionary.text(
        "Memory swap (e.g., 2g, 1024m):",
        default="2g",
        style=custom_style
    ).ask()
    
    if memory_swap is None:
        return
    
    # Get Dockerfile content or path
    dockerfile_type = questionary.select(
        "Dockerfile source:",
        choices=[
            "Inline content",
            "File path",
            "None (use default image)"
        ],
        style=custom_style
    ).ask()
    
    if dockerfile_type is None:
        return
    
    dockerfile_content = None
    dockerfile_path = None
    
    if dockerfile_type == "Inline content":
        console.print("\nEnter Dockerfile content (Ctrl+D to finish):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            dockerfile_content = "\n".join(lines)
    elif dockerfile_type == "File path":
        dockerfile_path = questionary.text(
            "Dockerfile path:",
            validate=lambda text: os.path.exists(text),
            style=custom_style
        ).ask()
        
        if dockerfile_path is None:
            return
    
    # Create the task
    data = {
        "name": name,
        "priority": priority.lower(),
        "resources": {
            "cpu_shares": int(cpu_shares),
            "memory": memory,
            "memory_swap": memory_swap
        }
    }
    
    if dockerfile_content:
        data["dockerfile_content"] = dockerfile_content
    if dockerfile_path:
        data["dockerfile_path"] = dockerfile_path
    
    result = api_request("tasks", method="POST", data=data)
    
    if result and "task_id" in result:
        console.print(f"[{THEME['success_color']}]Task created successfully. ID: {result['task_id']}[/{THEME['success_color']}]")
        
        # Ask if the user wants to start the task immediately
        start_now = questionary.confirm(
            "Start the task now?",
            default=True,
            style=custom_style
        ).ask()
        
        if start_now:
            start_result = api_request(f"tasks/{result['task_id']}/start", method="POST")
            if start_result:
                console.print(f"[{THEME['success_color']}]Task started successfully[/{THEME['success_color']}]")
            else:
                console.print(f"[{THEME['error_color']}]Failed to start task[/{THEME['error_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to create task[/{THEME['error_color']}]")


def start_task():
    """Start a task."""
    task_id = select_task()
    if not task_id:
        return
    
    result = api_request(f"tasks/{task_id}/start", method="POST")
    
    if result:
        console.print(f"[{THEME['success_color']}]Task started successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to start task[/{THEME['error_color']}]")


def stop_task():
    """Stop a task."""
    task_id = select_task()
    if not task_id:
        return
    
    checkpoint = questionary.confirm(
        "Create checkpoint before stopping?",
        default=True,
        style=custom_style
    ).ask()
    
    if checkpoint is None:
        return
    
    result = api_request(f"tasks/{task_id}/stop", method="POST", data={"checkpoint": checkpoint})
    
    if result:
        console.print(f"[{THEME['success_color']}]Task stopped successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to stop task[/{THEME['error_color']}]")


def resume_task():
    """Resume a task."""
    task_id = select_task()
    if not task_id:
        return
    
    result = api_request(f"tasks/{task_id}/resume", method="POST")
    
    if result:
        console.print(f"[{THEME['success_color']}]Task resumed successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to resume task[/{THEME['error_color']}]")


def delete_task():
    """Delete a task."""
    task_id = select_task()
    if not task_id:
        return
    
    confirm = questionary.confirm(
        "Are you sure you want to delete this task?",
        default=False,
        style=custom_style
    ).ask()
    
    if not confirm:
        return
    
    result = api_request(f"tasks/{task_id}", method="DELETE")
    
    if result:
        console.print(f"[{THEME['success_color']}]Task deleted successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to delete task[/{THEME['error_color']}]")


def system_submenu():
    """System management submenu."""
    while True:
        display_header()
        console.print("[bold]System Management[/bold]", justify="center")
        
        choice = questionary.select(
            "Select an option:",
            choices=[
                "System Status",
                "Rebalance Resources",
                "Start Scheduler",
                "Stop Scheduler",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if choice == "System Status":
            display_system_status()
        elif choice == "Rebalance Resources":
            rebalance_resources()
        elif choice == "Start Scheduler":
            start_scheduler()
        elif choice == "Stop Scheduler":
            stop_scheduler()
        elif choice == "Back to Main Menu" or choice is None:
            return
        
        # Wait for user input before returning to menu
        if choice is not None and choice != "Back to Main Menu":
            console.print("\nPress Enter to continue...", style="dim")
            input()


def display_system_status():
    """Display system status."""
    status = api_request("system/status")
    if not status:
        return
    
    # System resources
    resources = status.get('resources', {})
    
    console.print("\n[bold cyan]System Status[/bold cyan]")
    console.print("\n[bold]Resources:[/bold]")
    
    resource_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    resource_table.add_column("Resource")
    resource_table.add_column("Value")
    
    resource_table.add_row("CPU Cores", str(resources.get('cpu', 'Unknown')))
    resource_table.add_row("Memory", bytes_to_human(resources.get('memory', 0)))
    resource_table.add_row("Memory Swap", bytes_to_human(resources.get('memory_swap', 0)))
    
    console.print(resource_table)
    
    # Task statistics
    tasks = status.get('tasks', {})
    
    console.print("\n[bold]Tasks:[/bold]")
    
    task_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    task_table.add_column("State")
    task_table.add_column("Count")
    
    task_table.add_row(format_task_state("running"), str(tasks.get('running', 0)))
    task_table.add_row(format_task_state("pending"), str(tasks.get('pending', 0)))
    task_table.add_row(format_task_state("paused"), str(tasks.get('paused', 0)))
    task_table.add_row(format_task_state("completed"), str(tasks.get('completed', 0)))
    task_table.add_row(format_task_state("failed"), str(tasks.get('failed', 0)))
    task_table.add_row("[bold]Total[/bold]", str(tasks.get('total', 0)))
    
    console.print(task_table)
    
    # Scheduler status
    scheduler_running = status.get('scheduler_running', False)
    console.print("\n[bold]Scheduler:[/bold]")
    if scheduler_running:
        console.print("[green]Running[/green]")
    else:
        console.print("[yellow]Stopped[/yellow]")


def rebalance_resources():
    """Rebalance system resources."""
    result = api_request("system/rebalance", method="POST")
    
    if result:
        console.print(f"[{THEME['success_color']}]Resources rebalanced successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to rebalance resources[/{THEME['error_color']}]")


def start_scheduler():
    """Start the scheduler."""
    result = api_request("scheduler/start", method="POST")
    
    if result:
        console.print(f"[{THEME['success_color']}]Scheduler started successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to start scheduler[/{THEME['error_color']}]")


def stop_scheduler():
    """Stop the scheduler."""
    result = api_request("scheduler/stop", method="POST")
    
    if result:
        console.print(f"[{THEME['success_color']}]Scheduler stopped successfully[/{THEME['success_color']}]")
    else:
        console.print(f"[{THEME['error_color']}]Failed to stop scheduler[/{THEME['error_color']}]")


def display_keyboard_shortcuts():
    """Display available keyboard shortcuts."""
    table = Table(title="Keyboard Shortcuts", box=box.ROUNDED)
    table.add_column("Key", style="cyan")
    table.add_column("Action", style="green")
    
    table.add_row("Ctrl+C", "Exit application")
    table.add_row("Ctrl+B", "Go back to previous screen")
    table.add_row("Ctrl+R", "Refresh current screen")
    
    console.print(table)


def interactive_mode():
    """Run the interactive CLI."""
    try:
        # Create navigation stack
        nav_stack = NavigationStack()
        
        while True:
            display_header()
            console.print("[bold]Main Menu[/bold]", justify="center")
            
            choice = questionary.select(
                "Select an option:",
                choices=[
                    "Container Management",
                    "Task Management",
                    "System Management",
                    "Keyboard Shortcuts",
                    "Exit"
                ],
                style=custom_style
            ).ask()
            
            if choice == "Container Management":
                container_submenu()
            elif choice == "Task Management":
                task_submenu()
            elif choice == "System Management":
                system_submenu()
            elif choice == "Keyboard Shortcuts":
                display_keyboard_shortcuts()
                console.print("\nPress Enter to continue...", style="dim")
                input()
            elif choice == "Exit" or choice is None:
                break
    
    except KeyboardInterrupt:
        console.print("\n[bold]Exiting...[/bold]")
    
    console.print(f"[{THEME['success_color']}]Goodbye![/{THEME['success_color']}]")


if __name__ == "__main__":
    interactive_mode() 