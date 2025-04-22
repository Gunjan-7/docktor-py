#!/usr/bin/env python3
"""
Docker Orchestration CLI

A modern, interactive CLI for managing Docker containers and orchestration tasks.
Features:
- Interactive mode with rich UI elements
- Live resource monitoring with htop-style visualization
- Command-line interface for scripting
- API integration with the Docker Orchestration service
- Fallback to direct Docker CLI commands when API is unavailable

This CLI can operate in two modes:
1. Full mode - When connected to the Docker Orchestration API server
2. Limited mode - Using direct Docker CLI commands when API is unavailable

Usage:
  python docker_orch_cli.py interactive  # Start interactive mode
  python docker_orch_cli.py --help       # Show all available commands
  python docker_orch_cli.py monitor      # Start the resource monitor
"""

import os
import sys
import time
import json
import subprocess
import requests
import psutil
import signal
import threading
import asyncio
import shutil
from typing import List, Dict, Any, Optional, Set, Union, Tuple
from datetime import datetime, timedelta
import traceback

import typer
from rich.console import Console, Group
from rich.table import Table, Column
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich import box
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.tree import Tree
from rich.align import Align
from rich.traceback import install as install_rich_traceback

from prompt_toolkit import PromptSession, HTML
from prompt_toolkit.completion import Completer, Completion, NestedCompleter
from prompt_toolkit.validation import Validator
from prompt_toolkit.shortcuts import checkboxlist_dialog
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

import questionary
from questionary import Style

# Initialize Typer app with command groups
app = typer.Typer(help="Modern Docker Orchestration CLI", add_completion=True)
container_app = typer.Typer(help="Container management commands")
task_app = typer.Typer(help="Task management commands")
system_app = typer.Typer(help="System management commands")
app.add_typer(container_app, name="container")
app.add_typer(task_app, name="task")
app.add_typer(system_app, name="system")

# Initialize Rich console with tracebacks
console = Console()
install_rich_traceback()

# API endpoint
API_URL = "http://localhost:5000/api"

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

# Terminal prompt style
prompt_style = PromptStyle.from_dict({
    'completion-menu.completion': 'bg:#008888 #ffffff',
    'completion-menu.completion.current': 'bg:#00aaaa #000000',
    'scrollbar.background': 'bg:#88aaaa',
    'scrollbar.button': 'bg:#222222',
})

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

# Configure key bindings
kb = KeyBindings()

@kb.add('c-c')
def _(event):
    """Exit when Control-C is pressed."""
    event.app.exit()

# Docker command autocomplete
class DockerCommandCompleter(Completer):
    """Advanced completer for Docker commands and resources"""
    
    def __init__(self):
        self.container_cache = {}
        self.image_cache = {}
        self.last_updated = datetime.now() - timedelta(minutes=10)  # Force initial update
        self._update_caches()
    
    def _update_caches(self):
        """Update container and image caches if needed"""
        now = datetime.now()
        if (now - self.last_updated).total_seconds() < 30:
            return  # Only update every 30 seconds
        
        try:
            # Update container cache
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
                text=True, capture_output=True, check=True
            )
            lines = result.stdout.strip().split('\n')
            self.container_cache = {}
            for line in lines:
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        self.container_cache[parts[0]] = parts[1]
            
            # Update image cache
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}"],
                text=True, capture_output=True, check=True
            )
            lines = result.stdout.strip().split('\n')
            self.image_cache = {}
            for line in lines:
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        self.image_cache[parts[0]] = parts[1]
            
            self.last_updated = now
        except Exception:
            # Silently fail - we'll just use an empty cache
            pass
    
    def get_completions(self, document, complete_event):
        """Get command completions based on context"""
        self._update_caches()
        
        # Get the word and line up to the cursor
        word = document.get_word_before_cursor()
        line = document.current_line_before_cursor.lstrip()
        
        # Main commands
        if not line or line.count(' ') == 0:
            commands = [
                'start', 'stop', 'restart', 'status', 'logs', 'ps', 
                'images', 'volumes', 'networks', 'tasks', 'monitor',
                'container', 'task', 'system', 'interactive'
            ]
            
            for command in commands:
                if command.startswith(word):
                    display_meta = {
                        'start': 'Start a container or task',
                        'stop': 'Stop a container or task',
                        'restart': 'Restart a container',
                        'status': 'Show status of all containers',
                        'logs': 'View container logs',
                        'ps': 'List containers',
                        'images': 'List images',
                        'volumes': 'List volumes',
                        'networks': 'List networks',
                        'tasks': 'List orchestrator tasks',
                        'monitor': 'Monitor system resources',
                        'container': 'Container management commands',
                        'task': 'Task management commands',
                        'system': 'System management commands',
                        'interactive': 'Start interactive mode'
                    }.get(command, '')
                    
                    yield Completion(command, start_position=-len(word),
                                    display=command,
                                    display_meta=display_meta)
        
        # Container subcommands
        elif line.startswith('container '):
            prefix = line[len('container '):].strip()
            if not ' ' in prefix:
                subcommands = ['list', 'start', 'stop', 'restart', 'logs', 'inspect', 'prune']
                for cmd in subcommands:
                    if cmd.startswith(word):
                        yield Completion(cmd, start_position=-len(word))
        
        # Task subcommands
        elif line.startswith('task '):
            prefix = line[len('task '):].strip()
            if not ' ' in prefix:
                subcommands = ['list', 'create', 'start', 'stop', 'resume', 'delete']
                for cmd in subcommands:
                    if cmd.startswith(word):
                        yield Completion(cmd, start_position=-len(word))
        
        # Container names for start/stop/logs
        elif any(line.startswith(f"{cmd} ") for cmd in ['start', 'stop', 'restart', 'logs']):
            for container_name in self.container_cache.keys():
                if container_name.startswith(word):
                    status = self.container_cache.get(container_name, "")
                    display_meta = f"Status: {status}"
                    yield Completion(container_name, start_position=-len(word),
                                    display=container_name,
                                    display_meta=display_meta)

# Resource monitoring class
class ResourceMonitor:
    """Monitor system and Docker resource usage"""
    
    def __init__(self, refresh_interval=1.0):
        self.refresh_interval = refresh_interval
        self.running = False
        self._key_thread = None
        self.terminal_width = shutil.get_terminal_size().columns
        self.terminal_height = shutil.get_terminal_size().lines
        # Historical data for graphs
        self.historical_cpu = []
        self.historical_mem = []
        self.max_history = 60  # Store up to 60 data points
        self.container_stats = {}
    
    def stop(self):
        """Stop monitoring and clean up resources"""
        self.running = False
        if self._key_thread and self._key_thread.is_alive():
            self._key_thread.join()
    
    def update_terminal_size(self):
        """Update terminal size dimensions"""
        self.terminal_width = shutil.get_terminal_size().columns
        self.terminal_height = shutil.get_terminal_size().lines
    
    def _watch_key_presses(self):
        """Thread function to watch for key presses to exit"""
        try:
            # Set terminal to unbuffered mode
            if os.name == 'nt':
                import msvcrt
                while self.running:
                    if msvcrt.kbhit():
                        try:
                            key = msvcrt.getch().decode('utf-8', errors='replace').lower()
                            if key == 'q':
                                self.running = False
                                break
                        except Exception:
                            # Ignore any decoding errors
                            pass
                    time.sleep(0.1)
            else:
                import tty
                import termios
                import sys
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    while self.running:
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            try:
                                key = sys.stdin.read(1).lower()
                                if key == 'q':
                                    self.running = False
                                    break
                            except Exception:
                                # Ignore any reading errors
                                pass
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception as e:
            console.print(f"[red]Error in key watcher: {str(e)}[/]")
    
    def start(self):
        """Start monitoring and setup key watcher"""
        self.running = True
        # Start the key watcher thread
        self._key_thread = threading.Thread(target=self._watch_key_presses)
        self._key_thread.daemon = True
        self._key_thread.start()
    
    def run(self):
        """Run the resource monitor until stopped"""
        self.start()
        
        try:
            console.print("[cyan]Resource monitor running. Press 'q' to exit...[/]")
            
            # On Windows, msvcrt might not work well with Rich console
            # So we'll use the thread-based key checker
            while self.running:
                self.update_terminal_size()
                try:
                    self._display_system_resources()
                except Exception as e:
                    console.print(f"[red]Error displaying resources: {str(e)}[/]")
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            console.print("[yellow]Caught keyboard interrupt, shutting down...[/]")
        except Exception as e:
            console.print(f"[bold red]Error in monitor: {str(e)}[/]")
            traceback.print_exc()
        finally:
            self.stop()
    
    def _get_cpu_cores_usage(self):
        """Get CPU usage per core"""
        cpu_percent = psutil.cpu_percent(percpu=True)
        return cpu_percent
    
    def _get_network_stats(self):
        """Get network stats"""
        net_io = psutil.net_io_counters()
        return {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv,
        }
    
    def _get_disk_io_stats(self):
        """Get disk I/O stats"""
        disk_io = psutil.disk_io_counters()
        if disk_io:
            return {
                'read_count': disk_io.read_count,
                'write_count': disk_io.write_count,
                'read_bytes': disk_io.read_bytes,
                'write_bytes': disk_io.write_bytes,
            }
        return {}
    
    def _get_container_stats(self):
        """Get Docker container stats"""
        try:
            # Get container stats using Docker API
            result = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", 
                 "{{.Name}}\t{{.ID}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"]
            ).decode().strip().split('\n')
            
            # Parse the output
            containers = []
            for line in result:
                if not line:
                    continue
                    
                parts = line.split('\t')
                if len(parts) >= 8:
                    name, id, cpu, mem_usage, mem_perc, net_io, block_io, pids = parts[:8]
                    
                    # Clean percentages
                    cpu = cpu.rstrip('%')
                    mem_perc = mem_perc.rstrip('%')
                    
                    containers.append({
                        'name': name,
                        'id': id,
                        'cpu': float(cpu) if cpu else 0,
                        'memory_usage': mem_usage,
                        'memory_percent': float(mem_perc) if mem_perc else 0,
                        'network_io': net_io,
                        'block_io': block_io,
                        'pids': int(pids) if pids else 0
                    })
            
            # Update the container stats
            self.container_stats = {c['name']: c for c in containers}
            return containers
        except Exception as e:
            return []
    
    def _create_cpu_bars(self, cpus):
        """Create CPU usage bars for visualization"""
        bars = []
        for i, cpu in enumerate(cpus):
            bar_color = "green"
            if cpu > 60:
                bar_color = "yellow"
            if cpu > 85:
                bar_color = "red"
                
            # Calculate width based on percentage
            width = int(cpu / 2)  # Up to 50 characters for 100%
            # Use ASCII characters instead of Unicode
            bar = f"CPU{i:2d} [{('#' * width)}{('.' * (50 - width))}] {cpu:5.1f}%"
            bars.append(f"[{bar_color}]{bar}[/{bar_color}]")
        
        return bars
    
    def _create_sparkline(self, data, width=50):
        """Create a simple sparkline graph from historical data"""
        if not data:
            return ""
            
        # Use ASCII characters instead of Unicode blocks for better compatibility
        # blocks = " ▁▂▃▄▅▆▇█"
        blocks = " _.,-=+*#@"
        
        # Normalize data to 0-8 range (for the 9 ASCII characters)
        min_val = min(data) if data else 0
        max_val = max(data) if data else 100
        range_val = max_val - min_val
        
        if range_val == 0:
            normalized = [1] * len(data)  # Avoid division by zero
        else:
            normalized = [int(8 * (x - min_val) / range_val) for x in data]
        
        # Trim to width
        if len(normalized) > width:
            normalized = normalized[-width:]
        
        # Create the sparkline
        line = ''.join(blocks[n] for n in normalized)
        
        return line
    
    def _monitor_resources(self):
        """Main monitoring function that updates the display"""
        # Create layout for the dashboard
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="footer", size=1)
        )
        
        # Split the body into sections
        layout["body"].split_row(
            Layout(name="system", ratio=2),
            Layout(name="containers", ratio=3)
        )
        
        # Split the system section into CPU, memory and disk
        layout["system"].split_column(
            Layout(name="cpu", ratio=2),
            Layout(name="memory", ratio=1),
            Layout(name="disk", ratio=1),
            Layout(name="network", ratio=1)
        )
        
        with Live(layout, refresh_per_second=2, screen=True) as live:
            while self.running:
                try:
                    # Get system stats
                    cpu_percent = psutil.cpu_percent()
                    cpu_cores = self._get_cpu_cores_usage()
                    memory = psutil.virtual_memory()
                    swap = psutil.swap_memory()
                    disk = psutil.disk_usage('/')
                    net_stats = self._get_network_stats()
                    disk_io = self._get_disk_io_stats()
                    
                    # Store historical data
                    self.historical_cpu.append(cpu_percent)
                    if len(self.historical_cpu) > self.max_history:
                        self.historical_cpu = self.historical_cpu[-self.max_history:]
                        
                    self.historical_mem.append(memory.percent)
                    if len(self.historical_mem) > self.max_history:
                        self.historical_mem = self.historical_mem[-self.max_history:]
                    
                    # Get Docker container stats
                    containers = self._get_container_stats()
                    
                    # Create header
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    header = Text(f"{THEME['app_title']} Monitor - {now}", style=THEME["title_color"])
                    layout["header"].update(header)
                    
                    # Create footer with exit instructions
                    footer = Text("Press 'q' to exit the monitor", style="bold yellow")
                    layout["footer"].update(footer)
                    
                    # Create CPU panel
                    cpu_bars = self._create_cpu_bars(cpu_cores)
                    cpu_panel = Panel(
                        Group(
                            Text(f"CPU Total: {cpu_percent}%"),
                            Text(f"CPU History: {self._create_sparkline(self.historical_cpu)}"),
                            *cpu_bars
                        ),
                        title="CPU Usage",
                        border_style=THEME["border_style"],
                        box=THEME["border"]
                    )
                    layout["cpu"].update(cpu_panel)
                    
                    # Create memory panel
                    memory_used_gb = memory.used / (1024 * 1024 * 1024)
                    memory_total_gb = memory.total / (1024 * 1024 * 1024)
                    memory_panel = Panel(
                        Group(
                            Text(f"Memory: {memory.percent}% ({memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB)"),
                            Text(f"Memory History: {self._create_sparkline(self.historical_mem)}"),
                            Text(f"Swap: {swap.percent}% ({swap.used / (1024*1024*1024):.1f}GB / {swap.total / (1024*1024*1024):.1f}GB)")
                        ),
                        title="Memory",
                        border_style=THEME["border_style"],
                        box=THEME["border"]
                    )
                    layout["memory"].update(memory_panel)
                    
                    # Create disk panel
                    disk_panel = Panel(
                        Group(
                            Text(f"Disk Usage: {disk.percent}% ({disk.used / (1024*1024*1024):.1f}GB / {disk.total / (1024*1024*1024):.1f}GB)"),
                            Text(f"Read: {disk_io.get('read_bytes', 0) / (1024*1024):.1f}MB, Write: {disk_io.get('write_bytes', 0) / (1024*1024):.1f}MB") if disk_io else Text("No disk I/O data")
                        ),
                        title="Disk",
                        border_style=THEME["border_style"],
                        box=THEME["border"]
                    )
                    layout["disk"].update(disk_panel)
                    
                    # Create network panel
                    network_panel = Panel(
                        Group(
                            Text(f"Sent: {net_stats['bytes_sent'] / (1024*1024):.1f}MB ({net_stats['packets_sent']} packets)"),
                            Text(f"Received: {net_stats['bytes_recv'] / (1024*1024):.1f}MB ({net_stats['packets_recv']} packets)")
                        ),
                        title="Network",
                        border_style=THEME["border_style"],
                        box=THEME["border"]
                    )
                    layout["network"].update(network_panel)
                    
                    # Create containers panel
                    if containers:
                        container_table = Table(box=box.SIMPLE)
                        container_table.add_column("Name", style="cyan")
                        container_table.add_column("CPU%", justify="right", style="green")
                        container_table.add_column("Mem Usage", justify="right", style="yellow")
                        container_table.add_column("Mem%", justify="right", style="yellow")
                        container_table.add_column("Net I/O", style="blue")
                        container_table.add_column("Block I/O", style="magenta")
                        container_table.add_column("PIDs", justify="right", style="dim")
                        
                        for container in containers:
                            container_table.add_row(
                                container['name'],
                                f"{container['cpu']:.1f}%",
                                container['memory_usage'],
                                f"{container['memory_percent']:.1f}%",
                                container['network_io'],
                                container['block_io'],
                                str(container['pids'])
                            )
                            
                        container_panel = Panel(
                            container_table,
                            title=f"Docker Containers ({len(containers)})",
                            border_style=THEME["border_style"],
                            box=THEME["border"]
                        )
                    else:
                        container_panel = Panel(
                            "No running containers",
                            title="Docker Containers",
                            border_style=THEME["border_style"],
                            box=THEME["border"]
                        )
                    
                    layout["containers"].update(container_panel)
                
                except Exception as e:
                    # If something goes wrong, show the error
                    error_panel = Panel(
                        str(e),
                        title="Error",
                        border_style="red",
                        box=THEME["border"]
                    )
                    layout["body"].update(error_panel)
                
                time.sleep(1)

    def _display_system_resources(self):
        """Display system resources in a formatted way"""
        try:
            # Clear the screen
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # Get system stats
            cpu_percent = psutil.cpu_percent()
            cpu_cores = self._get_cpu_cores_usage()
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disk = psutil.disk_usage('/')
            net_stats = self._get_network_stats()
            disk_io = self._get_disk_io_stats()
            
            # Update historical data
            self.historical_cpu.append(cpu_percent)
            if len(self.historical_cpu) > self.max_history:
                self.historical_cpu = self.historical_cpu[-self.max_history:]
                
            self.historical_mem.append(memory.percent)
            if len(self.historical_mem) > self.max_history:
                self.historical_mem = self.historical_mem[-self.max_history:]
            
            # Get container stats
            containers = self._get_container_stats()
            
            # Create console output
            console = Console()
            
            # Create header
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"[bold {THEME['title_color']}]{THEME['app_title']} Resource Monitor - {now}[/]")
            console.print("Press 'q' to exit safely", style="bold yellow")
            console.print()
            
            # CPU section
            console.print("[bold]CPU Usage[/]")
            console.print(f"Total CPU: {cpu_percent}%")
            console.print(f"CPU History: {self._create_sparkline(self.historical_cpu)}")
            
            # Display per-core usage
            for i, cpu in enumerate(cpu_cores):
                bar_color = "green"
                if cpu > 60:
                    bar_color = "yellow"
                if cpu > 85:
                    bar_color = "red"
                
                # Calculate width based on percentage and terminal width
                max_bar_width = self.terminal_width - 20
                width = min(int((max_bar_width * cpu) / 100), max_bar_width)
                # Use ASCII characters for the bar
                bar = f"CPU{i:2d} [{'#' * width}{' ' * (max_bar_width - width)}] {cpu:5.1f}%"
                console.print(f"[{bar_color}]{bar}[/{bar_color}]")
            
            console.print()
            
            # Memory section
            console.print("[bold]Memory Usage[/]")
            memory_used_gb = memory.used / (1024 * 1024 * 1024)
            memory_total_gb = memory.total / (1024 * 1024 * 1024)
            console.print(f"Memory: {memory.percent}% ({memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB)")
            console.print(f"Memory History: {self._create_sparkline(self.historical_mem)}")
            console.print(f"Swap: {swap.percent}% ({swap.used / (1024*1024*1024):.1f}GB / {swap.total / (1024*1024*1024):.1f}GB)")
            console.print()
            
            # Disk section
            console.print("[bold]Disk Usage[/]")
            console.print(f"Disk: {disk.percent}% ({disk.used / (1024*1024*1024):.1f}GB / {disk.total / (1024*1024*1024):.1f}GB)")
            if disk_io:
                console.print(f"Read: {disk_io.get('read_bytes', 0) / (1024*1024):.1f}MB, Write: {disk_io.get('write_bytes', 0) / (1024*1024):.1f}MB")
            console.print()
            
            # Network section
            console.print("[bold]Network Usage[/]")
            console.print(f"Sent: {net_stats['bytes_sent'] / (1024*1024):.1f}MB ({net_stats['packets_sent']} packets)")
            console.print(f"Received: {net_stats['bytes_recv'] / (1024*1024):.1f}MB ({net_stats['packets_recv']} packets)")
            console.print()
            
            # Docker containers section
            console.print(f"[bold]Docker Containers ({len(containers)})[/]")
            if containers:
                table = Table(show_header=True, header_style="bold")
                table.add_column("Name", style="cyan")
                table.add_column("CPU%", justify="right", style="green")
                table.add_column("Mem Usage", justify="right", style="yellow")
                table.add_column("Mem%", justify="right", style="yellow")
                table.add_column("Net I/O", style="blue")
                table.add_column("Block I/O", style="magenta")
                table.add_column("PIDs", justify="right", style="dim")
                
                for container in containers:
                    table.add_row(
                        container['name'],
                        f"{container['cpu']:.1f}%",
                        container['memory_usage'],
                        f"{container['memory_percent']:.1f}%",
                        container['network_io'],
                        container['block_io'],
                        str(container['pids'])
                    )
                console.print(table)
            else:
                console.print("[yellow]No running containers[/]")
            
            console.print("\n[bold yellow]Press 'q' to exit the monitor[/]")
            
        except Exception as e:
            console = Console()
            console.print(f"[bold red]Error displaying resources: {str(e)}[/]")
            traceback.print_exc()

# Helper functions
def run_docker_command(command: List[str], show_output: bool = True) -> str:
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Running command..."),
        transient=True,
    ) as progress:
        task = progress.add_task("", total=None)
        try:
            if show_output:
                result = subprocess.run(command, text=True, capture_output=True)
                if result.returncode == 0:
                    console.print(f"[bold green]✓[/] Command completed successfully")
                    if result.stdout:
                        console.print(result.stdout)
                    return result.stdout
                else:
                    console.print(f"[bold red]✗[/] Command failed")
                    if result.stderr:
                        console.print(f"[red]{result.stderr}[/]")
                    return result.stderr
            else:
                subprocess.run(command)
                return ""
        except Exception as e:
            console.print(f"[bold red]✗[/] Error: {str(e)}")
            return str(e)

# API helper functions
def api_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
    """Make an API request to the orchestration service"""
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=2)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=2)
        elif method == "PUT":
            response = requests.put(url, json=data, timeout=2)
        elif method == "DELETE":
            response = requests.delete(url, timeout=2)
        else:
            return {"error": f"Unsupported method: {method}"}
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to the Docker Orchestration API server. Is it running?", "api_unavailable": True}
    except requests.exceptions.Timeout:
        return {"error": "Connection to Docker Orchestration API server timed out", "api_unavailable": True}
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {str(e)}"}

def format_task_state(state: str) -> Text:
    """Format task state with appropriate color"""
    color = THEME["task_state_colors"].get(state.lower(), "white")
    return Text(state, style=color)

def format_time(timestamp: Optional[float]) -> str:
    """Format timestamp into human-readable format"""
    if not timestamp:
        return "N/A"
    
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def bytes_to_human(size_bytes: int) -> str:
    """Convert bytes to human-readable format"""
    if size_bytes == 0:
        return "0B"
    
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.2f}{size_name[i]}"

def run_command_with_spinner(command: str, args: List[str], description: str = "Running command...") -> Tuple[int, str, str]:
    """Run a command with a spinner and return output"""
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]{description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("", total=None)
        
        try:
            result = subprocess.run(
                [command] + args,
                text=True,
                capture_output=True
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

def run_command_with_live_output(command: str, args: List[str], timeout: int = None) -> int:
    """Run a command with live output streaming"""
    try:
        # Start the process
        process = subprocess.Popen(
            [command] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Read and display output in real-time
        for line in iter(process.stdout.readline, ''):
            console.print(line, end="")
        
        # Wait for process to complete
        return_code = process.wait(timeout=timeout)
        return return_code
    except subprocess.TimeoutExpired:
        console.print("[yellow]Command timed out[/]")
        return 1
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/]")
        return 1

def select_containers(multi: bool = False, message: str = "Select container(s):") -> Union[str, List[str]]:
    """Interactive container selection"""
    containers = get_available_containers()
    
    # Check if no real containers are available
    if not containers or containers == ["No containers found"] or (len(containers) == 1 and not containers[0]):
        console.print("[yellow]No containers available[/]")
        return [] if multi else None
    
    if multi:
        # Multiple selection using checkbox dialog
        selections = checkboxlist_dialog(
            title="Container Selection",
            text=message,
            values=[(container, container) for container in containers]
        ).run()
        
        return selections or []
    else:
        # Single selection using questionary
        return questionary.select(
            message,
            choices=containers,
            style=custom_style
        ).ask()

# System app commands
@system_app.command("status")
def system_status():
    """Show system status overview"""
    with console.status("[bold blue]Fetching system status...", spinner="dots"):
        result = api_request("system/status")
    
    if "error" in result:
        console.print(f"[bold red]Error: {result['error']}[/]")
        return
    
    # Create a layout for the dashboard
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="body")
    )
    
    # Split the body into system info and task counts
    layout["body"].split_row(
        Layout(name="system_info", ratio=1),
        Layout(name="task_counts", ratio=1)
    )
    
    # Create the header
    header = Text(f"{THEME['app_title']} System Status", style=THEME["title_color"])
    layout["header"].update(header)
    
    # Create system info table
    sys_table = Table(box=THEME["border"])
    sys_table.add_column("Metric", style="cyan")
    sys_table.add_column("Value", style="green")
    
    sys_table.add_row("Docker Version", result.get("docker_version", "Unknown"))
    sys_table.add_row("Containers Running", str(result.get("containers_running", 0)))
    sys_table.add_row("Containers Paused", str(result.get("containers_paused", 0)))
    sys_table.add_row("Containers Stopped", str(result.get("containers_stopped", 0)))
    sys_table.add_row("Images", str(result.get("images", 0)))
    sys_table.add_row("Managed Containers", str(result.get("managed_containers", 0)))
    sys_table.add_row("CPU Usage", result.get("cpu_usage", "N/A"))
    sys_table.add_row("Memory Usage", result.get("memory_usage", "N/A"))
    
    # Create task counts table
    task_counts = result.get("task_counts", {})
    task_table = Table(box=THEME["border"])
    task_table.add_column("Task State", style="cyan")
    task_table.add_column("Count", style="green")
    
    for state, count in task_counts.items():
        state_color = THEME["task_state_colors"].get(state.lower(), "white")
        task_table.add_row(Text(state, style=state_color), str(count))
    
    # Update the layout
    layout["system_info"].update(Panel(sys_table, title="System Information", border_style=THEME["border_style"]))
    layout["task_counts"].update(Panel(task_table, title="Task Counts", border_style=THEME["border_style"]))
    
    # Print the dashboard
    console.print(layout)

@system_app.command("rebalance")
def system_rebalance():
    """Rebalance resources among running tasks"""
    with console.status("[bold blue]Rebalancing resources...", spinner="dots"):
        result = api_request("system/rebalance", method="POST")
    
    if "error" in result:
        console.print(f"[bold red]Error: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Resources rebalanced successfully")

@system_app.command("monitor")
def system_monitor():
    """Monitor system resources"""
    console.print("[bold cyan]Starting system resource monitor. Press 'q' to exit safely, or CTRL+C to force exit.[/]")
    
    monitor = ResourceMonitor()
    try:
        # Run the monitor
        monitor.run()
    except KeyboardInterrupt:
        console.print("[yellow]Forced exit of monitor...[/]")
    except Exception as e:
        console.print(f"[bold red]Error in monitor: {str(e)}[/]")
    finally:
        monitor.stop()
        console.print("[green]Resource monitor stopped successfully[/]")

@system_app.command("scheduler")
def scheduler_control(action: str = typer.Argument(..., help="Action to perform: 'start' or 'stop'")):
    """Control the job scheduler"""
    if action.lower() not in ["start", "stop"]:
        console.print("[bold red]Error: Action must be 'start' or 'stop'[/]")
        return
    
    with console.status(f"[bold blue]{action.capitalize()}ing scheduler...", spinner="dots"):
        result = api_request(f"scheduler/{action.lower()}", method="POST")
    
    if "error" in result:
        console.print(f"[bold red]Error: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Scheduler {action.lower()}ed: {result.get('status', '')}")

# Main app commands
@app.command()
def status():
    """Show status of all containers and tasks"""
    system_status()
    
    console.print("\n")
    with console.status("[bold blue]Fetching containers...", spinner="dots"):
        container_result = api_request("containers")
    
    if "containers" in container_result and not "error" in container_result:
        display_container_table(container_result.get("containers", []))
    else:
        if "error" in container_result:
            console.print(f"[bold red]Error fetching containers: {container_result['error']}[/]")
    
    console.print("\n")
    with console.status("[bold blue]Fetching tasks...", spinner="dots"):
        tasks = get_tasks()
    
    display_task_table(tasks)

@app.command()
def monitor():
    """Monitor system resources including CPU, memory, disk, and network"""
    console.print("[bold cyan]Starting resource monitor. Press 'q' to exit safely, or CTRL+C to force exit.[/]")
    
    # Create and start the monitor
    monitor = ResourceMonitor()
    try:
        # Run the monitor
        monitor.run()
    except KeyboardInterrupt:
        console.print("[yellow]Forced exit of monitor...[/]")
    except Exception as e:
        console.print(f"[bold red]Error in monitor: {str(e)}[/]")
    finally:
        monitor.stop()
        console.print("[green]Resource monitor stopped successfully[/]")

@app.command()
def logs(container: str = typer.Argument(None, help="Container name to view logs"),
         follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
         tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show")):
    """View container logs"""
    container_logs(container, follow, tail)

@app.command()
def start(container: str = typer.Argument(None, help="Container name to start"),
          wait: bool = typer.Option(False, "--wait", "-w", help="Wait for container to exit"),
          interactive: bool = typer.Option(False, "--interactive", "-i", help="Start in interactive mode")):
    """
    Start a container by name. If the container doesn't exist, it will attempt to:
    1. Create a container with that name from an image with the same name if it exists locally
    2. Pull the image with that name from a registry if it doesn't exist locally
    """
    if interactive:
        interactive_mode()
        return
    
    if not container:
        console.print("[bold red]Error:[/] Container name is required")
        return
    
    api_available = True
    task_id = None
    
    # Check if container exists
    returncode, stdout, stderr = run_command_with_spinner(
        "docker", ["container", "inspect", container],
        f"Checking if container {container} exists..."
    )
    
    # If container doesn't exist, try to create it from an image with the same name
    if returncode != 0:
        console.print(f"[yellow]Container {container} does not exist.[/]")
        
        # Check if image exists locally
        returncode, stdout, stderr = run_command_with_spinner(
            "docker", ["image", "inspect", container],
            f"Checking if image {container} exists locally..."
        )
        
        if returncode != 0:
            console.print(f"[yellow]Image {container} not found locally. Pulling from registry...[/]")
            
            # Try to pull the image from registry
            pull_code, pull_out, pull_err = run_command_with_spinner(
                "docker", ["pull", container],
                f"Pulling image {container}..."
            )
            
            if pull_code != 0:
                console.print(f"[bold red]FAILED[/] Failed to pull image {container}")
                console.print(f"[red]{pull_err}[/]")
                return
            else:
                console.print(f"[bold green]SUCCESS[/] Image {container} pulled successfully")
        
        # Now create and start a container from the image
        start_container_from_image(container, container, wait)
        return
    
    # Start the existing container
    with console.status(f"[bold blue]Starting container {container}...", spinner="dots"):
        # Find task ID associated with the container
        result = api_request("containers")
        
        if result.get("api_unavailable"):
            api_available = False
        elif "containers" in result:
            for c in result["containers"]:
                if c.get("name") == container:
                    task_id = c.get("task_id")
                    break
        
        if api_available and task_id:
            # Use the orchestrator API
            result = api_request(f"tasks/{task_id}/start", method="POST")
            if "error" in result:
                console.print(f"[bold red]Error: {result['error']}[/]")
                console.print("[yellow]Falling back to Docker CLI...[/]")
                api_available = False
            else:
                if result.get("status") == "started":
                    console.print(f"[bold green]SUCCESS[/] Container {container} started successfully")
                else:
                    console.print(f"[bold yellow]WARNING[/] Container start requested, but status is {result.get('status', 'unknown')}")
        
        if not api_available:
            # Use Docker CLI directly
            start_args = ["start"]
            if wait:
                start_args.append("--wait")
            start_args.append(container)
            
            returncode, stdout, stderr = run_command_with_spinner(
                "docker", start_args, 
                f"Starting container {container}..."
            )
            
            if returncode == 0:
                console.print(f"[bold green]SUCCESS[/] Container {container} started successfully")
            else:
                console.print(f"[bold red]FAILED[/] Failed to start container {container}")
                if stderr:
                    console.print(f"[red]{stderr}[/]")

def start_container_from_image(container_name: str, image_name: str, wait: bool = False):
    """Create and start a container from an image, pulling if necessary"""
    # Check if image exists locally, otherwise pull it
    with console.status(f"[bold blue]Checking for image {image_name}...", spinner="dots"):
        returncode, stdout, stderr = run_command_with_spinner(
            "docker", ["image", "inspect", image_name],
            f"Checking if image {image_name} exists locally..."
        )
        
        if returncode != 0:
            console.print(f"[yellow]Image {image_name} not found locally. Pulling from registry...[/]")
            
            pull_code, pull_out, pull_err = run_command_with_spinner(
                "docker", ["pull", image_name],
                f"Pulling image {image_name}..."
            )
            
            if pull_code != 0:
                console.print(f"[bold red]FAILED[/] Failed to pull image {image_name}")
                console.print(f"[red]{pull_err}[/]")
                return
            else:
                console.print(f"[bold green]SUCCESS[/] Image {image_name} pulled successfully")
    
    # Create and start a new container
    with console.status(f"[bold blue]Creating container {container_name} from image {image_name}...", spinner="dots"):
        returncode, stdout, stderr = run_command_with_spinner(
            "docker", ["create", "--name", container_name, image_name],
            f"Creating container {container_name}..."
        )
        
        if returncode != 0:
            console.print(f"[bold red]FAILED[/] Failed to create container {container_name}")
            console.print(f"[red]{stderr}[/]")
            return
    
    console.print(f"[bold green]SUCCESS[/] Created container {container_name} from image {image_name}")
    
    # Start the newly created container
    start_args = ["start"]
    if wait:
        start_args.append("--wait")
    start_args.append(container_name)
    
    returncode, stdout, stderr = run_command_with_spinner(
        "docker", start_args, 
        f"Starting container {container_name}..."
    )
    
    if returncode == 0:
        console.print(f"[bold green]SUCCESS[/] Container {container_name} started successfully")
    else:
        console.print(f"[bold red]FAILED[/] Failed to start container {container_name}")
        if stderr:
            console.print(f"[red]{stderr}[/]")

@app.command()
def stop(container: str = typer.Argument(None, help="Container name to stop")):
    """Stop a Docker container"""
    container_stop(container)

@app.command()
def restart(container: str = typer.Argument(None, help="Container name to restart")):
    """Restart a Docker container"""
    container_restart(container)

@app.command()
def interactive():
    """Start interactive mode with a modern UI"""
    console.print(f"[bold {THEME['title_color']}]{THEME['app_title']} Interactive Mode[/]")
    console.print("[cyan]Use arrow keys to navigate, Enter to select, Ctrl+C to exit[/]")
    
    # Check API connection
    with console.status("[bold blue]Checking API connection...", spinner="dots"):
        api_result = api_request("system/status")
    
    api_available = not api_result.get("api_unavailable", False)
    if not api_available:
        console.print(f"[yellow]{api_result.get('error')}[/]")
        console.print("[yellow]Running in limited mode - only Docker CLI commands will be available[/]")
    
    session = PromptSession(
        history=FileHistory('.docker_orch_history'),
        enable_history_search=True,
        completer=DockerCommandCompleter(),
        style=prompt_style,
        key_bindings=kb
    )
    
    while True:
        # Main menu choices depend on API availability
        choices = [
            {"name": "Container Management", "value": "container"},
            {"name": "Monitor Resources", "value": "monitor"},
            {"name": "Exit", "value": "exit"}
        ]
        
        # Add orchestration-specific options only if API is available
        if api_available:
            # Insert these at position 1 (after Container Management)
            choices.insert(1, {"name": "Task Management", "value": "task"})
            choices.insert(2, {"name": "System Management", "value": "system"})
        
        # Insert View Logs at position before last (before Exit)
        choices.insert(len(choices)-1, {"name": "View Logs", "value": "logs"})
        
        # Main menu
        action = questionary.select(
            "Select an action:",
            choices=choices,
            style=custom_style
        ).ask()
        
        if action == "exit" or action is None:
            break
        
        if action == "container":
            # Container management submenu - available in all modes
            container_submenu()
        
        elif action == "task" and api_available:
            # Task management submenu - only available with API
            task_submenu()
        
        elif action == "system" and api_available:
            # System management submenu - only available with API
            system_submenu()
        
        elif action == "logs":
            try:
                # Log viewing - available in all modes
                container = select_containers(message="Select container to view logs:")
                if container:
                    follow = questionary.confirm("Follow logs in real-time?", default=False, style=custom_style).ask()
                    tail = questionary.text(
                        "Number of lines to show:",
                        default="100",
                        validate=lambda text: text.isdigit(),
                        style=custom_style
                    ).ask()
                    
                    if follow:
                        # Stream logs in real-time
                        console.print(f"[cyan]Streaming logs for container {container}. Press Ctrl+C to stop.[/]")
                        try:
                            run_command_with_live_output("docker", ["logs", "--follow", f"--tail={tail}", container])
                        except KeyboardInterrupt:
                            console.print("[yellow]Stopped log streaming[/]")
                    else:
                        # Get logs
                        returncode, stdout, stderr = run_command_with_spinner(
                            "docker", ["logs", f"--tail={tail}", container], 
                            f"Fetching logs for {container}..."
                        )
                        
                        if returncode == 0:
                            # Display logs in a panel with syntax highlighting
                            log_panel = Panel(
                                Syntax(stdout, "log", theme="ansi_dark", word_wrap=True),
                                title=f"Logs for {container}",
                                border_style=THEME["border_style"],
                                box=THEME["border"],
                                padding=(1, 2),
                                highlight=True
                            )
                            console.print(log_panel)
                        else:
                            console.print(f"[bold red]Error fetching logs: {stderr}[/]")
                    
                    # Wait for user to press Enter before returning to menu
                    console.print("\n[dim]Press Enter to continue...[/]", end="")
                    input()
            except Exception as e:
                console.print(f"[bold red]Error: {str(e)}[/]")
                console.print("\n[dim]Press Enter to continue...[/]", end="")
                input()
        
        elif action == "monitor":
            # Monitoring - available in all modes
            try:
                monitor()
            except Exception as e:
                console.print(f"[bold red]Error: {str(e)}[/]")
                console.print("\n[dim]Press Enter to continue...[/]", end="")
                input()

@app.command()
def start_api_server():
    """Start the Docker Orchestration API server"""
    console.print("[bold blue]Starting API server...[/]")
    
    try:
        # Use subprocess to start the server in the background
        subprocess.Popen(["python", "docker-orch.py"], 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE)
        
        # Give it a moment to start
        time.sleep(2)
        
        # Check if it's running
        result = api_request("system/status")
        if not result.get("api_unavailable"):
            console.print("[bold green]✓[/] API server started successfully")
        else:
            console.print("[bold red]✗[/] API server failed to start properly")
    except Exception as e:
        console.print(f"[bold red]Error starting API server: {str(e)}[/]")

# Helper functions for interactive mode
def container_submenu():
    """Container management submenu"""
    while True:
        container_action = questionary.select(
            "Container Management:",
            choices=[
                "List Containers",
                "Start Container",
                "Stop Container",
                "Restart Container",
                "Inspect Container",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if container_action == "Back to Main Menu" or container_action is None:
            break
        
        try:
            if container_action == "List Containers":
                # Show both running and stopped containers
                all_containers = get_available_containers()
                if all_containers and all_containers != ["No containers found"]:
                    # Use direct Docker command for consistent output
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["ps", "-a"], 
                        "Listing all containers..."
                    )
                    if returncode == 0:
                        console.print(f"\n{stdout}")
                    else:
                        console.print(f"[bold red]Error listing containers: {stderr}[/]")
                else:
                    console.print("[yellow]No containers found[/]")
            
            elif container_action == "Start Container":
                # Get container name from user
                container_name = questionary.text(
                    "Enter container name to start:",
                    style=custom_style
                ).ask()
                
                if not container_name:
                    container = select_containers(message="Or select container to start:")
                    if container:
                        container_name = container
                
                if container_name:
                    # Check if container exists
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["container", "inspect", container_name],
                        f"Checking if container {container_name} exists..."
                    )
                    
                    # If container doesn't exist, try to create it from an image
                    if returncode != 0:
                        console.print(f"[yellow]Container {container_name} does not exist.[/]")
                        
                        # Check if image exists locally
                        returncode, stdout, stderr = run_command_with_spinner(
                            "docker", ["image", "inspect", container_name],
                            f"Checking if image {container_name} exists locally..."
                        )
                        
                        if returncode != 0:
                            console.print(f"[yellow]Image {container_name} not found locally. Pulling from registry...[/]")
                            
                            # Try to pull the image from registry
                            pull_code, pull_out, pull_err = run_command_with_spinner(
                                "docker", ["pull", container_name],
                                f"Pulling image {container_name}..."
                            )
                            
                            if pull_code != 0:
                                console.print(f"[bold red]✗[/] Failed to pull image {container_name}")
                                console.print(f"[red]{pull_err}[/]")
                            else:
                                console.print(f"[bold green]✓[/] Image {container_name} pulled successfully")
                                
                                # Create a container from the image
                                create_code, create_out, create_err = run_command_with_spinner(
                                    "docker", ["create", "--name", container_name, container_name],
                                    f"Creating container {container_name}..."
                                )
                                
                                if create_code != 0:
                                    console.print(f"[bold red]✗[/] Failed to create container {container_name}")
                                    console.print(f"[red]{create_err}[/]")
                                else:
                                    console.print(f"[bold green]✓[/] Container {container_name} created successfully")
                        else:
                            console.print(f"[green]Image {container_name} found locally[/]")
                            
                            # Create a container from the existing image
                            create_code, create_out, create_err = run_command_with_spinner(
                                "docker", ["create", "--name", container_name, container_name],
                                f"Creating container {container_name}..."
                            )
                            
                            if create_code != 0:
                                console.print(f"[bold red]✗[/] Failed to create container {container_name}")
                                console.print(f"[red]{create_err}[/]")
                            else:
                                console.print(f"[bold green]✓[/] Container {container_name} created successfully")
                    
                    # Now start the container (either existing or newly created)
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["start", container_name], 
                        f"Starting container {container_name}..."
                    )
                    
                    if returncode == 0:
                        console.print(f"[bold green]✓[/] Container {container_name} started successfully")
                    else:
                        console.print(f"[bold red]✗[/] Failed to start container {container_name}")
                        if stderr:
                            console.print(f"[red]{stderr}[/]")
            
            elif container_action == "Stop Container":
                # Select a container to stop
                container = select_containers(message="Select container to stop:")
                if container:
                    # Use direct Docker command
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["stop", container], 
                        f"Stopping container {container}..."
                    )
                    
                    if returncode == 0:
                        console.print(f"[bold green]✓[/] Container {container} stopped successfully")
                    else:
                        console.print(f"[bold red]✗[/] Failed to stop container {container}")
                        if stderr:
                            console.print(f"[red]{stderr}[/]")
            
            elif container_action == "Restart Container":
                # Select a container to restart
                container = select_containers(message="Select container to restart:")
                if container:
                    # Use direct Docker command
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["restart", container], 
                        f"Restarting container {container}..."
                    )
                    
                    if returncode == 0:
                        console.print(f"[bold green]✓[/] Container {container} restarted successfully")
                    else:
                        console.print(f"[bold red]✗[/] Failed to restart container {container}")
                        if stderr:
                            console.print(f"[red]{stderr}[/]")
            
            elif container_action == "Inspect Container":
                # Select a container to inspect
                container = select_containers(message="Select container to inspect:")
                if container:
                    # Use direct Docker command
                    returncode, stdout, stderr = run_command_with_spinner(
                        "docker", ["inspect", container], 
                        f"Inspecting container {container}..."
                    )
                    
                    if returncode == 0:
                        try:
                            # Try to parse as JSON for pretty display
                            container_info = json.loads(stdout)
                            # Create a formatted display
                            info_panel = Panel(
                                Syntax(json.dumps(container_info, indent=2), "json", theme="ansi_dark"),
                                title=f"Container Inspection: {container}",
                                border_style=THEME["border_style"],
                                box=THEME["border"],
                                padding=(1, 2),
                                highlight=True
                            )
                            console.print(info_panel)
                        except json.JSONDecodeError:
                            # If not valid JSON, just print the output
                            console.print(stdout)
                    else:
                        console.print(f"[bold red]✗[/] Failed to inspect container {container}")
                        if stderr:
                            console.print(f"[red]{stderr}[/]")
                
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/]")
            
        # Wait for user to press Enter before returning to menu
        console.print("\n[dim]Press Enter to continue...[/]", end="")
        input()

def task_submenu():
    """Task management submenu"""
    while True:
        task_action = questionary.select(
            "Task Management:",
            choices=[
                "List Tasks",
                "Create New Task",
                "Start Task",
                "Stop Task",
                "Resume Task",
                "Delete Task",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if task_action == "Back to Main Menu" or task_action is None:
            break
        
        if task_action == "List Tasks":
            task_list()
        
        elif task_action == "Create New Task":
            task_create()
        
        elif task_action == "Start Task":
            task_start()
        
        elif task_action == "Stop Task":
            task_stop()
        
        elif task_action == "Resume Task":
            task_resume()
        
        elif task_action == "Delete Task":
            task_delete()

def system_submenu():
    """System management submenu"""
    while True:
        system_action = questionary.select(
            "System Management:",
            choices=[
                "System Status",
                "Rebalance Resources",
                "Scheduler Control",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if system_action == "Back to Main Menu" or system_action is None:
            break
        
        if system_action == "System Status":
            system_status()
        
        elif system_action == "Rebalance Resources":
            system_rebalance()
        
        elif system_action == "Scheduler Control":
            scheduler_action = questionary.select(
                "Scheduler Action:",
                choices=["Start Scheduler", "Stop Scheduler"],
                style=custom_style
            ).ask()
            
            if scheduler_action == "Start Scheduler":
                scheduler_control("start")
            elif scheduler_action == "Stop Scheduler":
                scheduler_control("stop")

def get_available_containers() -> List[str]:
    """Get list of available containers"""
    try:
        # First try direct Docker CLI to ensure reliable results
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            text=True, capture_output=True, check=True
        )
        containers = result.stdout.strip().split('\n')
        containers = [c for c in containers if c]  # Filter out empty strings
        
        if containers:
            return containers
            
        # Fall back to API if Docker CLI failed or returned empty list
        api_result = api_request("containers")
        if "containers" in api_result and not "error" in api_result and not api_result.get("api_unavailable"):
            return [container["name"] for container in api_result["containers"]]
            
        return containers or ["No containers found"]
    except Exception as e:
        console.print(f"[yellow]Warning: Could not get container list: {str(e)}[/]")
        return ["No containers found"]  # Fallback

def get_running_containers() -> List[str]:
    """Get list of running containers"""
    try:
        # First try direct Docker CLI to ensure reliable results
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True, capture_output=True, check=True
        )
        containers = result.stdout.strip().split('\n')
        containers = [c for c in containers if c]  # Filter out empty strings
        
        if containers:
            return containers
            
        # Fall back to API if Docker CLI failed or returned empty list
        api_result = api_request("containers")
        if "containers" in api_result and not "error" in api_result and not api_result.get("api_unavailable"):
            return [container["name"] for container in api_result["containers"] 
                   if container.get("status", "") == "running"]
            
        return containers or ["No running containers"]
    except Exception as e:
        console.print(f"[yellow]Warning: Could not get running container list: {str(e)}[/]")
        return ["No running containers"]  # Fallback

def get_tasks(status_filter: str = None) -> List[Dict]:
    """Get list of all tasks"""
    endpoint = "tasks"
    if status_filter:
        endpoint += f"?status={status_filter}"
    
    result = api_request(endpoint)
    if "tasks" in result and not "error" in result:
        return result["tasks"]
    
    if "error" in result:
        console.print(f"[bold red]Error: {result['error']}[/]")
    
    return []

def display_container_table(containers: List[Dict]):
    """Display a formatted table of containers"""
    if not containers:
        console.print("[yellow]No containers found[/]")
        return
    
    table = Table(title="Docker Containers", box=THEME["border"])
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Task ID", style="blue")
    table.add_column("Task Name", style="magenta")
    table.add_column("Priority", style="dim")
    
    for container in containers:
        status_style = "green" if container.get("status") == "running" else "yellow"
        
        table.add_row(
            container.get("id", "")[:12],
            container.get("name", ""),
            Text(container.get("status", ""), style=status_style),
            container.get("task_id", ""),
            container.get("task_name", ""),
            container.get("priority", "")
        )
    
    console.print(table)

def display_task_table(tasks: List[Dict]):
    """Display a formatted table of tasks"""
    if not tasks:
        console.print("[yellow]No tasks found[/]")
        return
    
    table = Table(title="Orchestrator Tasks", box=THEME["border"])
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("State", style="yellow")
    table.add_column("Priority", style="blue")
    table.add_column("CPU", style="magenta")
    table.add_column("Memory", style="dim")
    table.add_column("Created", style="dim")
    
    for task in tasks:
        state = task.get("state", "unknown")
        state_text = format_task_state(state)
        
        # Format dates
        created = format_time(task.get("created_at"))
        
        # Format resources
        resources = task.get("resources", {})
        cpu = f"{resources.get('cpu_shares', 0)}"
        memory = resources.get("memory", "N/A")
        
        table.add_row(
            task.get("id", ""),
            task.get("name", ""),
            state_text,
            task.get("priority", ""),
            cpu,
            memory,
            created
        )
    
    console.print(table)

def stream_logs(container_id: str):
    """Stream logs from a container with real-time updates"""
    try:
        console.print(f"[cyan]Streaming logs for container {container_id}. Press Ctrl+C to stop.[/]")
        
        # Start the log streaming process - container_id can be a name or ID
        process = subprocess.Popen(
            ["docker", "logs", "--follow", container_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Read and display output in real-time
        try:
            for line in iter(process.stdout.readline, ''):
                console.print(line, end="")
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped log streaming[/]")
        finally:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't respond
                process.kill()
            
    except Exception as e:
        console.print(f"[bold red]Error streaming logs: {str(e)}[/]")

# Container app commands
@container_app.command("list")
def container_list(all: bool = typer.Option(True, "--all", "-a", help="Show all containers including stopped ones")):
    """List all containers managed by the orchestrator"""
    with console.status("[bold blue]Fetching containers...", spinner="dots"):
        result = api_request("containers")
    
    # If API is unavailable, fall back to direct Docker CLI
    if result.get("api_unavailable"):
        console.print(f"[yellow]{result.get('error')}[/]")
        console.print("[yellow]Falling back to Docker CLI...[/]")
        
        try:
            # Use docker CLI directly
            args = ["docker", "ps"]
            if all:
                args.append("-a")
                
            returncode, stdout, stderr = run_command_with_spinner(
                "docker", args[1:],
                f"Fetching {'all' if all else 'running'} containers..."
            )
            
            if returncode == 0:
                console.print(f"\n{stdout}")
                return
            else:
                console.print(f"[bold red]Error: {stderr}[/]")
                return
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/]")
            return
    
    if "error" in result:
        console.print(f"[bold red]Error: {result['error']}[/]")
        return
    
    containers = result.get("containers", [])
    if all:
        display_container_table(containers)
    else:
        # Filter for running containers only
        running = [c for c in containers if c.get("status") == "running"]
        display_container_table(running)

@container_app.command("stop")
def container_stop(
    container: str = typer.Argument(None, help="Container name to stop"),
    checkpoint: bool = typer.Option(True, "--checkpoint", "-c", help="Checkpoint the container before stopping"),
):
    """Stop a Docker container"""
    if not container:
        container = select_containers(message="Select container to stop:")
        if not container:
            return
    
    # First try API if available
    api_available = True
    task_id = None
    
    with console.status(f"[bold blue]Stopping container {container}...", spinner="dots"):
        # Find task ID associated with the container
        result = api_request("containers")
        
        if result.get("api_unavailable"):
            api_available = False
        elif "containers" in result:
            for c in result["containers"]:
                if c.get("name") == container:
                    task_id = c.get("task_id")
                    break
        
        if api_available and task_id:
            # Use the orchestrator API
            result = api_request(f"tasks/{task_id}/stop", method="POST", data={"checkpoint": checkpoint})
            if "error" in result:
                console.print(f"[bold red]Error: {result['error']}[/]")
                return
            
            if result.get("status") == "stopped":
                console.print(f"[bold green]SUCCESS[/] Container {container} stopped successfully")
            else:
                console.print(f"[bold yellow]WARNING[/] Container stop requested, but status is {result.get('status', 'unknown')}")
        else:
            # Use Docker CLI directly
            returncode, stdout, stderr = run_command_with_spinner(
                "docker", ["stop", container], 
                f"Stopping container {container}..."
            )
            
            if returncode == 0:
                console.print(f"[bold green]SUCCESS[/] Container {container} stopped successfully")
            else:
                console.print(f"[bold red]FAILED[/] Failed to stop container {container}")
                if stderr:
                    console.print(f"[red]{stderr}[/]")

@container_app.command("restart")
def container_restart(container: str = typer.Argument(None, help="Container name to restart")):
    """Restart a Docker container"""
    if not container:
        container = select_containers(message="Select container to restart:")
        if not container:
            return
    
    container_stop(container, checkpoint=False)
    container_start(container)

@container_app.command("logs")
def container_logs(
    container: str = typer.Argument(None, help="Container name to view logs"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show"),
):
    """View container logs"""
    if not container:
        container = select_containers(message="Select container to view logs:")
        if not container:
            return
    
    # First try to get container ID from API
    container_id = container
    api_available = True
    result = api_request("containers")
    
    if result.get("api_unavailable"):
        api_available = False
    elif "containers" in result:
        for c in result["containers"]:
            if c.get("name") == container:
                container_id = c.get("id")
                break
    
    if follow:
        # Stream logs in real-time
        stream_logs(container_id)
    else:
        # Get logs with API or docker command
        with console.status(f"[bold blue]Fetching logs for {container}...", spinner="dots"):
            logs = ""
            if api_available:
                try:
                    result = api_request(f"containers/{container_id}/logs?tail={tail}")
                    if "error" not in result:
                        logs = result.get("logs", "")
                    else:
                        raise Exception(result.get("error"))
                except Exception:
                    api_available = False
            
            if not api_available:
                # Use Docker CLI directly
                returncode, stdout, stderr = run_command_with_spinner(
                    "docker", ["logs", f"--tail={tail}", container_id], 
                    f"Fetching logs for {container}..."
                )
                
                logs = stdout if returncode == 0 else stderr
        
        # Display logs in a panel with syntax highlighting
        log_panel = Panel(
            Syntax(logs, "log", theme="ansi_dark", word_wrap=True),
            title=f"Logs for {container}",
            border_style=THEME["border_style"],
            box=THEME["border"],
            padding=(1, 2),
            highlight=True
        )
        console.print(log_panel)

@container_app.command("inspect")
def container_inspect(container: str = typer.Argument(None, help="Container name to inspect")):
    """Inspect a container's details"""
    if not container:
        container = select_containers(message="Select container to inspect:")
        if not container:
            return
    
    # Find container ID
    container_id = container
    api_available = True
    result = api_request("containers")
    
    if result.get("api_unavailable"):
        api_available = False
    elif "containers" in result:
        for c in result["containers"]:
            if c.get("name") == container:
                container_id = c.get("id")
                break
    
    with console.status(f"[bold blue]Inspecting container {container}...", spinner="dots"):
        health_info = {}
        
        if api_available:
            # Try API first
            result = api_request(f"containers/{container_id}/health")
            if "error" not in result:
                health_info = result
            else:
                api_available = False
        
        if not api_available:
            # Use Docker CLI directly
            returncode, stdout, stderr = run_command_with_spinner(
                "docker", ["inspect", container_id], 
                f"Inspecting container {container}..."
            )
            
            if returncode == 0:
                try:
                    health_info = json.loads(stdout)[0]
                except json.JSONDecodeError:
                    health_info = {"error": "Failed to parse container info"}
            else:
                health_info = {"error": stderr}
    
    # Display container info
    if "error" in health_info:
        console.print(f"[bold red]Error: {health_info['error']}[/]")
        return
    
    # Create a formatted display
    info_panel = Panel(
        Syntax(json.dumps(health_info, indent=2), "json", theme="ansi_dark"),
        title=f"Container Inspection: {container}",
        border_style=THEME["border_style"],
        box=THEME["border"],
        padding=(1, 2),
        highlight=True
    )
    console.print(info_panel)

# Task app commands
@task_app.command("list")
def task_list(
    status: str = typer.Option(None, "--status", "-s", help="Filter by task status"),
    all: bool = typer.Option(True, "--all", "-a", help="Show all tasks")
):
    """List all tasks in the orchestrator"""
    with console.status("[bold blue]Fetching tasks...", spinner="dots"):
        tasks = get_tasks(status)
    
    display_task_table(tasks)

@task_app.command("create")
def task_create():
    """Create a new task interactively"""
    # Collect task information interactively
    name = questionary.text("Task name:", style=custom_style).ask()
    if not name:
        console.print("[yellow]Task creation cancelled[/]")
        return
    
    priority = questionary.select(
        "Select priority:",
        choices=["low", "medium", "high", "critical"],
        default="medium",
        style=custom_style
    ).ask()
    
    # Resources
    cpu_shares = questionary.text(
        "CPU shares (e.g. 1024):",
        default="1024",
        validate=lambda text: text.isdigit(),
        style=custom_style
    ).ask()
    
    memory = questionary.text(
        "Memory limit (e.g. 1g, 512m):",
        default="1g",
        style=custom_style
    ).ask()
    
    # Define how to run the task
    task_type = questionary.select(
        "How do you want to define the task?",
        choices=["Dockerfile", "Docker Compose", "Existing Image"],
        style=custom_style
    ).ask()
    
    dockerfile_content = None
    dockerfile_path = None
    compose_content = None
    compose_path = None
    
    if task_type == "Dockerfile":
        dockerfile_choice = questionary.select(
            "Dockerfile source:",
            choices=["Enter content", "Specify path"],
            style=custom_style
        ).ask()
        
        if dockerfile_choice == "Enter content":
            console.print("[cyan]Enter Dockerfile content (end with a line containing only 'EOF'):[/]")
            lines = []
            while True:
                line = input()
                if line == "EOF":
                    break
                lines.append(line)
            dockerfile_content = "\n".join(lines)
        else:
            dockerfile_path = questionary.text(
                "Dockerfile path:",
                style=custom_style
            ).ask()
    
    elif task_type == "Docker Compose":
        compose_choice = questionary.select(
            "Docker Compose source:",
            choices=["Enter content", "Specify path"],
            style=custom_style
        ).ask()
        
        if compose_choice == "Enter content":
            console.print("[cyan]Enter Docker Compose content (end with a line containing only 'EOF'):[/]")
            lines = []
            while True:
                line = input()
                if line == "EOF":
                    break
                lines.append(line)
            compose_content = "\n".join(lines)
        else:
            compose_path = questionary.text(
                "Docker Compose file path:",
                style=custom_style
            ).ask()
    
    # Create the task
    with console.status("[bold blue]Creating task...", spinner="dots"):
        task_data = {
            "name": name,
            "priority": priority,
            "resources": {
                "cpu_shares": int(cpu_shares),
                "memory": memory,
                "memory_swap": f"{int(memory[:-1]) * 2}{memory[-1]}" if memory[-1].isalpha() else f"{int(memory) * 2}m"
            }
        }
        
        if dockerfile_content:
            task_data["dockerfile_content"] = dockerfile_content
        if dockerfile_path:
            task_data["dockerfile_path"] = dockerfile_path
        if compose_content:
            task_data["compose_content"] = compose_content
        if compose_path:
            task_data["compose_path"] = compose_path
        
        result = api_request("tasks", method="POST", data=task_data)
    
    if "error" in result:
        console.print(f"[bold red]Error creating task: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Task created successfully with ID: {result.get('task_id')}")
        
        # Ask if user wants to start the task immediately
        if questionary.confirm("Start task now?", default=False, style=custom_style).ask():
            task_start(result.get('task_id'))

@task_app.command("start")
def task_start(task_id: str = typer.Argument(None, help="Task ID to start")):
    """Start a task"""
    if not task_id:
        # List pending tasks for selection
        with console.status("[bold blue]Fetching pending tasks...", spinner="dots"):
            tasks = get_tasks("pending")
        
        if not tasks:
            console.print("[yellow]No pending tasks available to start[/]")
            return
        
        task_choices = [f"{t['id']} - {t['name']}" for t in tasks]
        selected = questionary.select(
            "Select task to start:",
            choices=task_choices,
            style=custom_style
        ).ask()
        
        if not selected:
            return
        
        # Extract task ID from selection
        task_id = selected.split(" - ")[0]
    
    with console.status(f"[bold blue]Starting task {task_id}...", spinner="dots"):
        result = api_request(f"tasks/{task_id}/start", method="POST")
    
    if "error" in result:
        console.print(f"[bold red]Error starting task: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Task {task_id} started successfully")

@task_app.command("stop")
def task_stop(
    task_id: str = typer.Argument(None, help="Task ID to stop"),
    checkpoint: bool = typer.Option(True, "--checkpoint", "-c", help="Checkpoint the task before stopping")
):
    """Stop a running task"""
    if not task_id:
        # List running tasks for selection
        with console.status("[bold blue]Fetching running tasks...", spinner="dots"):
            tasks = get_tasks("running")
        
        if not tasks:
            console.print("[yellow]No running tasks available to stop[/]")
            return
        
        task_choices = [f"{t['id']} - {t['name']}" for t in tasks]
        selected = questionary.select(
            "Select task to stop:",
            choices=task_choices,
            style=custom_style
        ).ask()
        
        if not selected:
            return
        
        # Extract task ID from selection
        task_id = selected.split(" - ")[0]
    
    with console.status(f"[bold blue]Stopping task {task_id}...", spinner="dots"):
        result = api_request(f"tasks/{task_id}/stop", method="POST", data={"checkpoint": checkpoint})
    
    if "error" in result:
        console.print(f"[bold red]Error stopping task: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Task {task_id} stopped successfully")

@task_app.command("resume")
def task_resume(task_id: str = typer.Argument(None, help="Task ID to resume")):
    """Resume a paused task"""
    if not task_id:
        # List paused tasks for selection
        with console.status("[bold blue]Fetching paused tasks...", spinner="dots"):
            tasks = get_tasks("paused")
        
        if not tasks:
            console.print("[yellow]No paused tasks available to resume[/]")
            return
        
        task_choices = [f"{t['id']} - {t['name']}" for t in tasks]
        selected = questionary.select(
            "Select task to resume:",
            choices=task_choices,
            style=custom_style
        ).ask()
        
        if not selected:
            return
        
        # Extract task ID from selection
        task_id = selected.split(" - ")[0]
    
    with console.status(f"[bold blue]Resuming task {task_id}...", spinner="dots"):
        result = api_request(f"tasks/{task_id}/resume", method="POST")
    
    if "error" in result:
        console.print(f"[bold red]Error resuming task: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Task {task_id} resumed successfully")

@task_app.command("delete")
def task_delete(task_id: str = typer.Argument(None, help="Task ID to delete")):
    """Delete a task"""
    if not task_id:
        # List all tasks for selection
        with console.status("[bold blue]Fetching tasks...", spinner="dots"):
            tasks = get_tasks()
        
        if not tasks:
            console.print("[yellow]No tasks available to delete[/]")
            return
        
        task_choices = [f"{t['id']} - {t['name']} ({t['state']})" for t in tasks]
        selected = questionary.select(
            "Select task to delete:",
            choices=task_choices,
            style=custom_style
        ).ask()
        
        if not selected:
            return
        
        # Extract task ID from selection
        task_id = selected.split(" - ")[0]
    
    # Confirm deletion
    confirm = questionary.confirm(
        f"Are you sure you want to delete task {task_id}? This cannot be undone.",
        default=False,
        style=custom_style
    ).ask()
    
    if not confirm:
        console.print("[yellow]Task deletion cancelled[/]")
        return
    
    with console.status(f"[bold blue]Deleting task {task_id}...", spinner="dots"):
        result = api_request(f"tasks/{task_id}", method="DELETE")
    
    if "error" in result:
        console.print(f"[bold red]Error deleting task: {result['error']}[/]")
    else:
        console.print(f"[bold green]✓[/] Task {task_id} deleted successfully")

if __name__ == "__main__":
    # Register signal handler for clean exit
    def signal_handler(sig, frame):
        console.print("\n[yellow]Exiting...[/]")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the CLI
    app()