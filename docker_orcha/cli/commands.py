"""
CLI commands for the Docker Orchestration System.

This module provides the command-line interface commands for managing Docker containers and tasks.
"""

import os
import time
import sys
import requests
import typer
from typing import List, Dict, Optional, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.prompt import Prompt, Confirm

from docker_orcha.models.enums import Priority, TaskState
from docker_orcha.utils.formatting import format_time, bytes_to_human, format_duration


# API URL
API_URL = "http://localhost:5000/api"

# Initialize Typer app with command groups
app = typer.Typer(help="Modern Docker Orchestration CLI", add_completion=True)
container_app = typer.Typer(help="Container management commands")
task_app = typer.Typer(help="Task management commands")
system_app = typer.Typer(help="System management commands")
app.add_typer(container_app, name="container")
app.add_typer(task_app, name="task")
app.add_typer(system_app, name="system")

# Initialize Rich console
console = Console()


def api_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
    """
    Make a request to the API.
    
    Args:
        endpoint: API endpoint
        method: HTTP method
        data: Request data
        
    Returns:
        Dict: API response
    """
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    
    try:
        if method == "GET":
            response = requests.get(url)
        elif method == "POST":
            response = requests.post(url, json=data)
        elif method == "PUT":
            response = requests.put(url, json=data)
        elif method == "DELETE":
            response = requests.delete(url)
        else:
            console.print(f"[bold red]Error:[/bold red] Unsupported HTTP method: {method}")
            return {}
        
        if response.status_code >= 400:
            console.print(f"[bold red]Error ({response.status_code}):[/bold red] {response.text}")
            return {}
        
        return response.json()
    except requests.RequestException as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        return {}


def format_task_state(state: str) -> str:
    """Format task state with appropriate color."""
    colors = {
        "pending": "yellow",
        "running": "green",
        "paused": "cyan",
        "completed": "blue",
        "failed": "red"
    }
    return f"[{colors.get(state, 'white')}]{state}[/{colors.get(state, 'white')}]"


@system_app.command("status")
def system_status():
    """Show system status."""
    status = api_request("system/status")
    if not status:
        return
    
    # System resources
    resources = status.get('resources', {})
    
    console.print("\n[bold cyan]System Status[/bold cyan]")
    console.print("\n[bold]Resources:[/bold]")
    
    resource_table = Table(show_header=True, header_style="bold magenta")
    resource_table.add_column("Resource")
    resource_table.add_column("Value")
    
    resource_table.add_row("CPU Cores", str(resources.get('cpu', 'Unknown')))
    resource_table.add_row("Memory", bytes_to_human(resources.get('memory', 0)))
    resource_table.add_row("Memory Swap", bytes_to_human(resources.get('memory_swap', 0)))
    
    console.print(resource_table)
    
    # Task statistics
    tasks = status.get('tasks', {})
    
    console.print("\n[bold]Tasks:[/bold]")
    
    task_table = Table(show_header=True, header_style="bold magenta")
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


@system_app.command("rebalance")
def system_rebalance():
    """Rebalance system resources."""
    result = api_request("system/rebalance", method="POST")
    if result:
        console.print("\n[bold green]Successfully rebalanced system resources[/bold green]")


@container_app.command("list")
def container_list(all: bool = typer.Option(True, "--all", "-a", help="Show all containers including stopped ones")):
    """List containers."""
    containers = api_request("containers")
    if not containers:
        console.print("[yellow]No containers found[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
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
            container.get('task_id', ''),
            container.get('task_name', ''),
            container.get('priority', '')
        )
    
    console.print("\n[bold cyan]Containers[/bold cyan]")
    console.print(table)


@container_app.command("logs")
def container_logs(
    container: str = typer.Argument(None, help="Container name or ID to view logs"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show"),
):
    """View container logs."""
    if not container:
        containers = api_request("containers")
        if not containers:
            console.print("[yellow]No containers found[/yellow]")
            return
        
        # Select a container
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Index")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Status")
        
        for i, container_data in enumerate(containers):
            table.add_row(
                str(i + 1),
                container_data.get('id', '')[:12],
                container_data.get('name', ''),
                container_data.get('status', '')
            )
        
        console.print("\n[bold cyan]Select a container:[/bold cyan]")
        console.print(table)
        
        choice = Prompt.ask("Enter container index", default="1")
        try:
            index = int(choice) - 1
            if 0 <= index < len(containers):
                container = containers[index].get('id', '')
            else:
                console.print("[bold red]Invalid index[/bold red]")
                return
        except ValueError:
            console.print("[bold red]Invalid input[/bold red]")
            return
    
    logs = api_request(f"containers/{container}/logs?tail={tail}")
    if not logs:
        return
    
    # Display logs
    syntax = Syntax(logs.get('logs', ''), "log", theme="monokai", line_numbers=True)
    console.print(syntax)
    
    # Follow logs if requested
    if follow:
        console.print("[yellow]Following logs. Press Ctrl+C to stop.[/yellow]")
        try:
            last_line_count = len(logs.get('logs', '').split('\n'))
            while True:
                time.sleep(1)
                new_logs = api_request(f"containers/{container}/logs?tail={tail}")
                
                # Check if we got new logs
                if new_logs:
                    log_lines = new_logs.get('logs', '').split('\n')
                    if len(log_lines) > last_line_count:
                        # Print only new lines
                        new_content = '\n'.join(log_lines[-(len(log_lines) - last_line_count):])
                        console.print(new_content)
                        last_line_count = len(log_lines)
        except KeyboardInterrupt:
            console.print("[yellow]Stopped following logs[/yellow]")


@task_app.command("list")
def task_list(
    status: str = typer.Option(None, "--status", "-s", help="Filter by task status"),
    all: bool = typer.Option(True, "--all", "-a", help="Show all tasks")
):
    """List tasks."""
    url = "tasks"
    if status:
        url += f"?status={status}"
    
    tasks = api_request(url)
    if not tasks:
        console.print("[yellow]No tasks found[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
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


@app.command()
def start():
    """Start the API server."""
    try:
        from docker_orcha.api.server import start_api_server
        console.print("[bold green]Starting API server...[/bold green]")
        start_api_server(debug=True)
    except ImportError as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        console.print("[yellow]Make sure the Docker Orchestration System is installed correctly.[/yellow]")


@app.command()
def version():
    """Show version information."""
    try:
        from docker_orcha import __version__
        console.print(f"[bold cyan]Docker Orchestration System[/bold cyan] v{__version__}")
    except ImportError:
        console.print("[bold cyan]Docker Orchestration System[/bold cyan] (version unknown)")


@app.command()
def interactive():
    """Start the interactive mode."""
    try:
        from docker_orcha.cli.interactive import interactive_mode
        interactive_mode()
    except ImportError as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        console.print("[yellow]Make sure the interactive mode module is installed correctly.[/yellow]")


if __name__ == "__main__":
    app() 