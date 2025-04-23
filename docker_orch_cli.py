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

@kb.add('c-b')
def _(event):
    """Add keyboard shortcut for going back (Ctrl+B)"""
    # This will be picked up by interactive commands that support navigation
    event.app.exit(result={'action': 'back'})

@kb.add('c-f')
def _(event):
    """Add keyboard shortcut for going forward (Ctrl+F)"""
    # This will be picked up by interactive commands that support navigation
    event.app.exit(result={'action': 'forward'})

@kb.add('c-h')
def _(event):
    """Add keyboard shortcut for help (Ctrl+H)"""
    # Display a help screen or panel
    event.app.exit(result={'action': 'help'})

@kb.add('c-s')
def _(event):
    """Add keyboard shortcut for saving (Ctrl+S)"""
    # Signal that the user wants to save
    event.app.exit(result={'action': 'save'})

@kb.add('c-r')
def _(event):
    """Add keyboard shortcut for refreshing (Ctrl+R)"""
    # Signal that the user wants to refresh/reload
    event.app.exit(result={'action': 'refresh'})

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
                            if key == 'q' or key == '\x1b':  # q or ESC key
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
                                if key == 'q' or key == '\x1b':  # q or ESC key
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
            # Initial clear screen and instructions
            console.clear()
            console.print("[bold cyan]Resource Monitor[/]")
            console.print("[yellow]======================================[/]")
            console.print("[cyan]Press 'q' or ESC to exit the monitor safely[/]")
            console.print("[cyan](Using Ctrl+C will exit the entire application)[/]")
            console.print("[yellow]======================================[/]\n")
            
            # On Windows, msvcrt might not work well with Rich console
            # So we'll use the thread-based key checker
            while self.running:
                self.update_terminal_size()
                try:
                    self._display_system_resources()
                except Exception as e:
                    console.print(f"[red]Error displaying resources: {str(e)}[/]")
                time.sleep(self.refresh_interval)
            
            # Clear screen when exiting
            console.clear()
            console.print("[bold green]Resource monitor exited successfully[/]")
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
        """Display system resources in the console"""
        # Clear the console for a fresh display
        console.clear()
        
        # Header with instructions
        header = Panel(
            "[bold cyan]Resource Monitor[/] - Press [bold yellow]'q'[/] or [bold yellow]ESC[/] to exit safely",
            box=THEME["border"],
            style=THEME["border_style"],
            padding=(0, 2)
        )
        console.print(header)
        
        # Get system stats
        cpu_percent = psutil.cpu_percent()
        self.historical_cpu.append(cpu_percent)
        if len(self.historical_cpu) > self.max_history:
            self.historical_cpu.pop(0)
            
        memory = psutil.virtual_memory()
        self.historical_mem.append(memory.percent)
        if len(self.historical_mem) > self.max_history:
            self.historical_mem.pop(0)
            
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        net_stats = self._get_network_stats()
        
        # Get Docker container stats
        containers = self._get_container_stats()
        
        # Create CPU usage panel
        cpu_bars = self._create_cpu_bars(self._get_cpu_cores_usage())
        cpu_history = self._create_sparkline(self.historical_cpu, width=min(60, self.terminal_width - 20))
        
        cpu_content = [
            f"[bold]CPU Usage: {cpu_percent:.1f}%[/]",
            f"CPU History: {cpu_history}",
            ""
        ] + cpu_bars
        
        cpu_panel = Panel(
            "\n".join(cpu_content),
            title="CPU",
            border_style=THEME["border_style"], 
            box=THEME["border"]
        )
        
        # Create memory panel
        mem_used = memory.used / 1_000_000_000  # GB
        mem_total = memory.total / 1_000_000_000  # GB
        mem_history = self._create_sparkline(self.historical_mem, width=min(60, self.terminal_width - 20))
        
        swap_used = swap.used / 1_000_000_000  # GB
        swap_total = swap.total / 1_000_000_000  # GB
        
        memory_color = "green"
        if memory.percent > 60:
            memory_color = "yellow"
        if memory.percent > 85:
            memory_color = "red"
            
        swap_color = "green"
        if swap.percent > 60:
            swap_color = "yellow"
        if swap.percent > 85:
            swap_color = "red"
        
        mem_content = [
            f"[bold]Memory Usage: [{memory_color}]{memory.percent:.1f}%[/{memory_color}][/]",
            f"Memory History: {mem_history}",
            f"Used: {mem_used:.2f} GB / Total: {mem_total:.2f} GB",
            "",
            f"[bold]Swap Usage: [{swap_color}]{swap.percent:.1f}%[/{swap_color}][/]",
            f"Used: {swap_used:.2f} GB / Total: {swap_total:.2f} GB"
        ]
        
        memory_panel = Panel(
            "\n".join(mem_content),
            title="Memory",
            border_style=THEME["border_style"], 
            box=THEME["border"]
        )
        
        # Create disk panel
        disk_color = "green"
        if disk.percent > 70:
            disk_color = "yellow"
        if disk.percent > 90:
            disk_color = "red"
            
        disk_used = disk.used / 1_000_000_000  # GB
        disk_total = disk.total / 1_000_000_000  # GB
        
        disk_content = [
            f"[bold]Disk Usage (/) : [{disk_color}]{disk.percent:.1f}%[/{disk_color}][/]",
            f"Used: {disk_used:.2f} GB / Total: {disk_total:.2f} GB"
        ]
        
        # Add disk I/O stats if available
        disk_io = self._get_disk_io_stats()
        if disk_io:
            read_mb = disk_io['read_bytes'] / 1_000_000  # MB
            write_mb = disk_io['write_bytes'] / 1_000_000  # MB
            
            disk_content.extend([
                "",
                f"[bold]Disk I/O:[/]",
                f"Read: {read_mb:.2f} MB ({disk_io['read_count']} operations)",
                f"Write: {write_mb:.2f} MB ({disk_io['write_count']} operations)",
            ])
        
        disk_panel = Panel(
            "\n".join(disk_content),
            title="Disk",
            border_style=THEME["border_style"], 
            box=THEME["border"]
        )
        
        # Create network panel
        recv_mb = net_stats['bytes_recv'] / 1_000_000  # MB
        sent_mb = net_stats['bytes_sent'] / 1_000_000  # MB
        
        network_content = [
            f"[bold]Network Traffic:[/]",
            f"Received: {recv_mb:.2f} MB ({net_stats['packets_recv']} packets)",
            f"Sent: {sent_mb:.2f} MB ({net_stats['packets_sent']} packets)",
        ]
        
        network_panel = Panel(
            "\n".join(network_content),
            title="Network",
            border_style=THEME["border_style"], 
            box=THEME["border"]
        )
        
        # Create containers panel
        if containers:
            container_rows = []
            for c in sorted(containers, key=lambda x: x['name']):
                # Color code the CPU usage
                cpu_color = "green"
                if c['cpu'] > 60:
                    cpu_color = "yellow"
                if c['cpu'] > 85:
                    cpu_color = "red"
                    
                # Color code the memory usage
                mem_color = "green"
                if c['memory_percent'] > 60:
                    mem_color = "yellow"
                if c['memory_percent'] > 85:
                    mem_color = "red"
                
                container_rows.append(
                    f"[bold]{c['name']}[/] ({c['id'][:12]}): " +
                    f"CPU: [{cpu_color}]{c['cpu']:.1f}%[/{cpu_color}], " +
                    f"Mem: [{mem_color}]{c['memory_percent']:.1f}%[/{mem_color}] ({c['memory_usage']}), " +
                    f"Net: {c['network_io']}, IO: {c['block_io']}, PIDs: {c['pids']}"
                )
                
            containers_panel = Panel(
                "\n".join(container_rows) if container_rows else "No containers running",
                title=f"Docker Containers ({len(containers)})",
                border_style=THEME["border_style"], 
                box=THEME["border"]
            )
        else:
            containers_panel = Panel(
                "No containers running or unable to fetch container stats",
                title="Docker Containers",
                border_style=THEME["border_style"], 
                box=THEME["border"]
            )
            
        # Create layout
        layout = Table.grid()
        layout.add_column("col")
        
        # Add the panels to the layout
        layout.add_row(cpu_panel)
        layout.add_row(memory_panel)
        
        # Create a grid for disk and network panels
        disk_net_layout = Table.grid()
        disk_net_layout.add_column("half")
        disk_net_layout.add_column("half")
        disk_net_layout.add_row(disk_panel, network_panel)
        
        layout.add_row(disk_net_layout)
        layout.add_row(containers_panel)
        
        # Add footer with timestamp and exit instructions
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        footer = f"[dim]Last updated: {timestamp} - Press 'q' or ESC to exit safely[/dim]"
        
        # Print the layout
        console.print(layout)
        console.print(footer)

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
    console.print("[bold cyan]Starting system resource monitor. Press 'q' or ESC to exit safely, or CTRL+C to force exit.[/]")
    time.sleep(1)  # Give a moment to read the instructions
    
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
        console.print("[green]Resource monitor stopped.[/]")

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
    console.print("[bold cyan]Starting resource monitor. Press 'q' or ESC to exit safely, or CTRL+C to force exit.[/]")
    time.sleep(1)  # Give a moment to read the instructions
    
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
        console.print("[green]Resource monitor stopped.[/]")

@app.command()
def logs(container: str = typer.Argument(None, help="Container name to view logs"),
         follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
         tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show")):
    """View container logs"""
    container_logs(container, follow, tail)

@app.command()
def start(container: str = None, wait: bool = False):
    """
    Start a Docker container.
    If the container doesn't exist, try to create it from an image.
    If the image doesn't exist locally, try to pull it from a registry.
    """
    if container is None:
        console.print("[bold red]ERROR[/] Container name is required")
        return
        
    # Check if container exists
    returncode, stdout, stderr = run_command("docker", ["container", "inspect", container], capture_output=True)
    
    if returncode == 0:
        # Container exists, start it
        console.print(f"[yellow]Starting existing container {container}...[/]")
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
    else:
        # Container doesn't exist, try to create it from image
        console.print(f"[yellow]Container {container} doesn't exist, checking for image...[/]")
        
        # Try various image name formats
        image_variations = [
            container,                        # original name
            f"docker.io/library/{container}", # official Docker Hub image
            f"docker.io/{container}",         # Docker Hub user image
            f"{container}:latest"             # with latest tag
        ]
        
        # First check if any image exists locally
        found_locally = False
        local_image_name = None
        
        for img in image_variations:
            returncode, stdout, stderr = run_command("docker", ["image", "inspect", img], capture_output=True)
            if returncode == 0:
                # Image exists locally
                console.print(f"[green]Found image locally: {img}[/]")
                found_locally = True
                local_image_name = img
                break
        
        if found_locally and local_image_name:
            # Image exists locally
            start_container_from_image(container, local_image_name, wait)
        else:
            # Try to pull image from registry
            console.print(f"[yellow]Image not found locally, trying to pull from registry...[/]")
            
            # Try pulling variations of the image name
            for img in image_variations:
                console.print(f"[yellow]Trying to pull {img}...[/]")
                returncode, stdout, stderr = run_command_with_spinner(
                    "docker", ["pull", img],
                    f"Pulling image {img}..."
                )
                
                if returncode == 0:
                    console.print(f"[bold green]SUCCESS[/] Image {img} pulled successfully")
                    start_container_from_image(container, img, wait)
                    return
            
            # All pull attempts failed
            console.print(f"[bold red]FAILED[/] Failed to pull any image for {container}")
            console.print("[yellow]Please make sure the image name is correct and accessible[/]")
            console.print("[yellow]You can try: docker pull IMAGE_NAME first to troubleshoot[/]")

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
    console.print("[cyan]Press Ctrl+H at any time to display keyboard shortcuts help[/]")
    
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
        try:
            main_action = questionary.select(
                "Docker Orchestration CLI:",
                choices=[
                    "Container Management",
                    "Task Management",
                    "System Management",
                    "Help & Keyboard Shortcuts",
                    "Exit"
                ],
                style=custom_style
            ).ask()
            
            if main_action == "Exit" or main_action is None:
                break
            
            if main_action == "Container Management":
                container_submenu()
            
            elif main_action == "Task Management":
                task_submenu()
            
            elif main_action == "System Management":
                system_submenu()
            
            elif main_action == "Help & Keyboard Shortcuts":
                display_keyboard_shortcuts()
                
        except KeyboardInterrupt:
            break
    
    console.print("[bold green]Thank you for using Docker Orchestration CLI![/]")

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
                "Create Container",
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
            
            elif container_action == "Create Container":
                # Launch the container creation wizard
                console.print("[bold blue]Launching Container Creation Wizard...[/]")
                create_container_wizard()
            
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
                    
                    # If container exists, start it
                    if returncode == 0:
                        console.print(f"[green]Container {container_name} exists. Starting...[/]")
                        
                        # Start the container
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
                    # If container doesn't exist, try to create it from an image
                    else:
                        console.print(f"[yellow]Container {container_name} does not exist.[/]")
                        
                        # Try various image name formats
                        image_variations = [
                            container_name,                         # original name
                            f"docker.io/library/{container_name}",  # official Docker Hub image
                            f"docker.io/{container_name}",          # Docker Hub user image
                            f"{container_name}:latest"              # with latest tag
                        ]
                        
                        # First check if any image exists locally
                        found_locally = False
                        local_image_name = None
                        
                        for img in image_variations:
                            returncode, stdout, stderr = run_command(
                                "docker", ["image", "inspect", img],
                                capture_output=True
                            )
                            
                            if returncode == 0:
                                console.print(f"[green]Found image locally: {img}[/]")
                                found_locally = True
                                local_image_name = img
                                break
                        
                        if found_locally and local_image_name:
                            # Create a container from the local image
                            create_code, create_out, create_err = run_command_with_spinner(
                                "docker", ["create", "--name", container_name, local_image_name],
                                f"Creating container {container_name} from image {local_image_name}..."
                            )
                            
                            if create_code != 0:
                                console.print(f"[bold red]✗[/] Failed to create container {container_name}")
                                console.print(f"[red]{create_err}[/]")
                            else:
                                console.print(f"[bold green]✓[/] Container {container_name} created successfully")
                                
                                # Start the newly created container
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
                        else:
                            # Try to pull the image from registry
                            console.print(f"[yellow]Image not found locally. Attempting to pull from registry...[/]")
                            
                            pull_success = False
                            pulled_image = None
                            
                            for img in image_variations:
                                console.print(f"[yellow]Trying to pull {img}...[/]")
                                pull_code, pull_out, pull_err = run_command_with_spinner(
                                    "docker", ["pull", img],
                                    f"Pulling image {img}..."
                                )
                                
                                if pull_code == 0:
                                    console.print(f"[bold green]✓[/] Image {img} pulled successfully")
                                    pull_success = True
                                    pulled_image = img
                                    break
                            
                            if pull_success and pulled_image:
                                # Create a container from the pulled image
                                create_code, create_out, create_err = run_command_with_spinner(
                                    "docker", ["create", "--name", container_name, pulled_image],
                                    f"Creating container {container_name} from image {pulled_image}..."
                                )
                                
                                if create_code != 0:
                                    console.print(f"[bold red]✗[/] Failed to create container {container_name}")
                                    console.print(f"[red]{create_err}[/]")
                                else:
                                    console.print(f"[bold green]✓[/] Container {container_name} created successfully")
                                    
                                    # Start the newly created container
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
                            else:
                                console.print(f"[bold red]✗[/] Failed to pull any image for {container_name}")
                                console.print("[yellow]Please make sure the image name is correct and accessible[/]")
                                console.print("[yellow]You can try: docker pull IMAGE_NAME first to troubleshoot[/]")
            
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
        
        try:
            if task_action == "List Tasks":
                # Get task filter
                status_filter = questionary.select(
                    "Filter tasks by status:",
                    choices=[
                        "All Tasks",
                        "Pending Tasks",
                        "Running Tasks",
                        "Paused Tasks",
                        "Completed Tasks",
                        "Failed Tasks"
                    ],
                    style=custom_style
                ).ask()
                
                filter_value = None
                if status_filter != "All Tasks":
                    filter_value = status_filter.split()[0].lower()
                
                task_list(status=filter_value)
            
            elif task_action == "Create New Task":
                task_create()
            
            elif task_action == "Start Task":
                task_start()
            
            elif task_action == "Stop Task":
                # Add confirmation for checkpoint
                task_id = questionary.text(
                    "Enter Task ID to stop:",
                    style=custom_style
                ).ask()
                
                if task_id:
                    checkpoint = questionary.confirm(
                        "Checkpoint the task before stopping?",
                        default=True,
                        style=custom_style
                    ).ask()
                    
                    task_stop(task_id, checkpoint=checkpoint)
            
            elif task_action == "Resume Task":
                task_resume()
            
            elif task_action == "Delete Task":
                # Add confirmation for deletion
                task_id = questionary.text(
                    "Enter Task ID to delete:",
                    style=custom_style
                ).ask()
                
                if task_id:
                    confirm = questionary.confirm(
                        f"Are you sure you want to delete task {task_id}?",
                        default=False,
                        style=custom_style
                    ).ask()
                    
                    if confirm:
                        task_delete(task_id)
                    else:
                        console.print("[yellow]Task deletion cancelled[/]")
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/]")
        
        # Wait for user to press Enter before returning to menu
        console.print("\n[dim]Press Enter to continue...[/]", end="")
        input()

def system_submenu():
    """System management submenu"""
    while True:
        system_action = questionary.select(
            "System Management:",
            choices=[
                "System Status",
                "Resource Monitor",
                "Rebalance Resources",
                "Scheduler Control",
                "Help & Shortcuts",
                "Back to Main Menu"
            ],
            style=custom_style
        ).ask()
        
        if system_action == "Back to Main Menu" or system_action is None:
            break
        
        try:
            if system_action == "System Status":
                system_status()
            
            elif system_action == "Resource Monitor":
                console.print("[bold cyan]Starting resource monitor. Press 'q' or ESC to exit safely, or CTRL+C to force exit.[/]")
                monitor = ResourceMonitor()
                try:
                    monitor.run()
                except KeyboardInterrupt:
                    console.print("[yellow]Forced exit of monitor...[/]")
                except Exception as e:
                    console.print(f"[bold red]Error in monitor: {str(e)}[/]")
                finally:
                    monitor.stop()
                    console.print("[green]Resource monitor stopped successfully[/]")
            
            elif system_action == "Rebalance Resources":
                confirm = questionary.confirm(
                    "Are you sure you want to rebalance system resources?",
                    default=True,
                    style=custom_style
                ).ask()
                
                if confirm:
                    system_rebalance()
                else:
                    console.print("[yellow]Resource rebalance cancelled[/]")
            
            elif system_action == "Scheduler Control":
                scheduler_action = questionary.select(
                    "Scheduler Action:",
                    choices=[
                        "Start Scheduler",
                        "Stop Scheduler",
                        "Back"
                    ],
                    style=custom_style
                ).ask()
                
                if scheduler_action != "Back":
                    action = scheduler_action.split()[0].lower()
                    scheduler_control(action)
            
            elif system_action == "Help & Shortcuts":
                display_keyboard_shortcuts()
                
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/]")
        
        # Wait for user to press Enter before returning to menu
        if system_action != "Resource Monitor" and system_action != "Help & Shortcuts":
            console.print("\n[dim]Press Enter to continue...[/]", end="")
            input()

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

def select_docker_image():
    """Interactive Docker image selection with multiple modes"""
    # First ask which selection mode the user prefers
    selection_mode = questionary.select(
        "How would you like to select a Docker image?",
        choices=[
            "Type image name directly",
            "Choose from popular images",
            "Search Docker Hub"
        ],
        style=custom_style
    ).ask()
    
    if selection_mode == "Type image name directly":
        # Get image name via text input
        image = questionary.text(
            "Enter Docker image name (format: name:tag):",
            style=custom_style
        ).ask()
        return image
    
    elif selection_mode == "Choose from popular images":
        # Hardcoded list of popular images
        popular_images = [
            "ubuntu:latest",
            "alpine:latest",
            "nginx:latest",
            "python:3.9",
            "node:14",
            "mysql:8",
            "postgres:13",
            "redis:latest",
            "mongodb:latest",
            "Other (type manually)"
        ]
        
        image = questionary.select(
            "Select an image:",
            choices=popular_images,
            style=custom_style
        ).ask()
        
        if image == "Other (type manually)":
            # Fall back to manual entry
            image = questionary.text(
                "Enter Docker image name (format: name:tag):",
                style=custom_style
            ).ask()
        
        return image
    
    elif selection_mode == "Search Docker Hub":
        # Get search term
        search_term = questionary.text(
            "Enter search term:",
            style=custom_style
        ).ask()
        
        # Execute Docker search
        with console.status(f"[bold blue]Searching for '{search_term}'...", spinner="dots"):
            returncode, stdout, stderr = run_command_with_spinner(
                "docker", ["search", search_term, "--limit", "10"],
                f"Searching Docker Hub for '{search_term}'..."
            )
        
        if returncode == 0:
            # Parse results
            lines = stdout.strip().split('\n')[1:]  # Skip header
            images = []
            
            for line in lines:
                if line:
                    parts = line.split()
                    if parts:
                        images.append(parts[0])  # First column is image name
            
            images.append("Other (type manually)")
            
            # Let user select from results
            image = questionary.select(
                "Select an image:",
                choices=images,
                style=custom_style
            ).ask()
            
            if image == "Other (type manually)":
                # Fall back to manual entry
                image = questionary.text(
                    "Enter Docker image name (format: name:tag):",
                    style=custom_style
                ).ask()
                
            # If tag not specified, add :latest
            if ':' not in image:
                image += ":latest"
                
            return image
        else:
            console.print("[bold red]Error searching Docker Hub[/]")
            # Fall back to manual entry
            image = questionary.text(
                "Enter Docker image name (format: name:tag):",
                style=custom_style
            ).ask()
            return image

class ConfigPreview:
    """Class to handle configuration preview and updates"""
    
    def __init__(self, config_type="dockerfile"):
        """Initialize the configuration preview
        
        Args:
            config_type (str): Type of configuration ('dockerfile' or 'compose')
        """
        self.config_type = config_type
        self.config_lines = []
        self.services = {}  # For storing multiple services in docker-compose
        self.current_service = "app"  # Default service name
        self.initialize_default_config()
    
    def initialize_default_config(self):
        """Set up default configuration based on the type"""
        if self.config_type == "dockerfile":
            self.config_lines = [
                "FROM base_image:tag",
                "WORKDIR /app",
                "# Commands will be added here",
                "# Expose ports will be added here",
                "# Entrypoint will be added here"
            ]
        elif self.config_type == "compose":
            self.services = {
                "app": {
                    "image": "base_image:tag",
                    "ports": [],
                    "volumes": [],
                    "environment": {},
                    "command": ""
                }
            }
            self._regenerate_compose_config()
    
    def _regenerate_compose_config(self):
        """Regenerate the docker-compose config from services data"""
        self.config_lines = [
            "version: '3'",
            "services:"
        ]
        
        # Add each service
        for service_name, service_config in self.services.items():
            self.config_lines.append(f"  {service_name}:")
            self.config_lines.append(f"    image: {service_config['image']}")
            
            # Add ports if any
            if service_config['ports']:
                self.config_lines.append("    ports:")
                for port in service_config['ports']:
                    self.config_lines.append(f"      - \"{port}\"")
            
            # Add volumes if any
            if service_config['volumes']:
                self.config_lines.append("    volumes:")
                for volume in service_config['volumes']:
                    self.config_lines.append(f"      - {volume}")
            
            # Add environment if any
            if service_config['environment']:
                self.config_lines.append("    environment:")
                for key, value in service_config['environment'].items():
                    self.config_lines.append(f"      {key}: {value}")
            
            # Add command if specified
            if service_config['command']:
                self.config_lines.append(f"    command: {service_config['command']}")
        
        # Add networks and volumes configurations
        self.config_lines.append("# Networks and volumes will be configured here")
    
    def add_service(self, service_name):
        """Add a new service to the docker-compose configuration"""
        if self.config_type != "compose":
            return False
        
        if service_name in self.services:
            return False  # Service already exists
        
        self.services[service_name] = {
            "image": "base_image:tag",
            "ports": [],
            "volumes": [],
            "environment": {},
            "command": ""
        }
        
        self.current_service = service_name
        self._regenerate_compose_config()
        return True
    
    def set_current_service(self, service_name):
        """Set the current service for operations"""
        if self.config_type != "compose" or service_name not in self.services:
            return False
        
        self.current_service = service_name
        return True
    
    def update_base_image(self, image_name):
        """Update the base image in the configuration"""
        if self.config_type == "dockerfile":
            for i, line in enumerate(self.config_lines):
                if line.startswith("FROM "):
                    self.config_lines[i] = f"FROM {image_name}"
                    break
        elif self.config_type == "compose":
            # Update the current service's image
            self.services[self.current_service]["image"] = image_name
            self._regenerate_compose_config()
    
    def add_port(self, container_port, host_port=None):
        """Add a port mapping to the configuration"""
        if self.config_type == "dockerfile":
            # Find the expose ports comment line
            for i, line in enumerate(self.config_lines):
                if "# Expose ports" in line:
                    # Replace comment with actual EXPOSE directive
                    self.config_lines[i] = f"EXPOSE {container_port}"
                    break
        elif self.config_type == "compose":
            # Add port mapping to the current service
            port_mapping = f"{host_port}:{container_port}" if host_port else f"{container_port}"
            if port_mapping not in self.services[self.current_service]["ports"]:
                self.services[self.current_service]["ports"].append(port_mapping)
                self._regenerate_compose_config()
    
    def add_volume(self, host_path, container_path):
        """Add a volume mapping to the configuration"""
        if self.config_type == "dockerfile":
            # Dockerfile doesn't have volumes in the same way, could add VOLUME directive
            for i, line in enumerate(self.config_lines):
                if "# Commands" in line:
                    # Add VOLUME directive after WORKDIR
                    self.config_lines.insert(i, f"VOLUME [\"{container_path}\"]")
                    break
        elif self.config_type == "compose":
            # Add volume mapping to the current service
            volume_mapping = f"{host_path}:{container_path}"
            if volume_mapping not in self.services[self.current_service]["volumes"]:
                self.services[self.current_service]["volumes"].append(volume_mapping)
                self._regenerate_compose_config()
    
    def add_command(self, command):
        """Add a command (RUN, CMD, ENTRYPOINT) to the configuration"""
        if self.config_type == "dockerfile":
            for i, line in enumerate(self.config_lines):
                if "# Commands" in line:
                    # Replace comment with actual command
                    self.config_lines[i] = f"RUN {command}"
                    break
        elif self.config_type == "compose":
            # Set command for the current service
            self.services[self.current_service]["command"] = command
            self._regenerate_compose_config()
    
    def add_environment_variable(self, key, value):
        """Add an environment variable to the configuration"""
        if self.config_type == "dockerfile":
            # Find a place to insert the ENV directive
            for i, line in enumerate(self.config_lines):
                if "# Commands" in line:
                    # Add ENV directive after commands
                    self.config_lines.insert(i+1, f"ENV {key}={value}")
                    break
        elif self.config_type == "compose":
            # Add environment variable to the current service
            self.services[self.current_service]["environment"][key] = value
            self._regenerate_compose_config()
    
    def get_config_as_string(self):
        """Get the configuration as a formatted string"""
        return '\n'.join(self.config_lines)
    
    def display_config(self):
        """Display the current configuration in the console"""
        syntax = "Dockerfile" if self.config_type == "dockerfile" else "YAML"
        config_text = self.get_config_as_string()
        
        # Create a panel with the configuration
        panel = Panel(
            Syntax(config_text, syntax, theme="ansi_dark"),
            title=f"{'Dockerfile' if self.config_type == 'dockerfile' else 'Docker Compose'} Preview",
            border_style=THEME["border_style"],
            padding=(1, 2)
        )
        
        console.print(panel)

class NavigationStack:
    """Navigation stack to keep track of user's navigation through menus"""
    def __init__(self):
        self.stack = []
    
    def save_step(self, step_id, data=None):
        """Save the current step to the navigation stack"""
        if data is None:
            data = {}
        self.stack.append({"step_id": step_id, "data": data})
    
    def go_back(self):
        """Go back to the previous step and return its ID"""
        if len(self.stack) <= 1:
            return "config_type"  # Default to start if we can't go back further
        
        # Remove current step
        self.stack.pop()
        
        # Return the previous step
        return self.stack[-1]["step_id"]
    
    def clear(self):
        """Clear the navigation stack"""
        self.stack = []
    
    # Legacy methods for backwards compatibility
    def push(self, screen_id, data=None):
        """Push a screen onto the stack (legacy method)"""
        self.save_step(screen_id, data)
    
    def back(self):
        """Go back to the previous screen (legacy method)"""
        if len(self.stack) <= 1:
            return None
        self.stack.pop()
        return self.stack[-1]
    
    def can_go_back(self):
        """Check if we can go back (legacy method)"""
        return len(self.stack) > 1

def create_container_wizard():
    """Interactive wizard for creating Docker container or compose setup"""
    console.print("[bold]Container Creation Wizard[/bold]", style=THEME["title_style"])
    
    # Use the NavigationStack to keep track of steps
    nav_stack = NavigationStack()
    
    # Initialize configuration variables
    config_preview = None
    config_type = None
    container_name = ""
    service_names = []
    current_step = "config_type"
    
    while True:
        try:
            # Handle different steps based on the current_step
            if current_step == "config_type":
                nav_stack.save_step(current_step)
                console.print("Select configuration type:", style=THEME["info_style"])
                config_type = questionary.select(
                    "Configuration type:",
                    choices=["Dockerfile", "Docker Compose", "Cancel"],
                    style=questionary_style
                ).ask()
                
                if config_type == "Cancel":
                    console.print("Wizard canceled.", style=THEME["warning_style"])
                    return
                
                config_preview = ConfigPreview("dockerfile" if config_type == "Dockerfile" else "compose")
                current_step = "container_name" if config_type == "Dockerfile" else "service_setup"
            
            elif current_step == "container_name":
                nav_stack.save_step(current_step)
                container_name = questionary.text(
                    "Enter container name:",
                    style=questionary_style
                ).ask()
                
                if not container_name:
                    console.print("Container name cannot be empty.", style=THEME["error_style"])
                    continue
                
                current_step = "base_image"
            
            elif current_step == "service_setup":
                nav_stack.save_step(current_step)
                
                # For Docker Compose, set up services
                if not service_names:
                    # At least add the default 'app' service
                    service_names.append("app")
                
                # Show current services and allow adding more
                choices = [f"Configure Service: {name}" for name in service_names]
                choices.append("Add New Service")
                choices.append("Continue to Image Selection")
                choices.append("Go Back")
                
                service_action = questionary.select(
                    "Service Setup:",
                    choices=choices,
                    style=questionary_style
                ).ask()
                
                if service_action == "Add New Service":
                    new_service = questionary.text(
                        "Enter new service name:",
                        style=questionary_style
                    ).ask()
                    
                    if new_service and new_service not in service_names:
                        service_names.append(new_service)
                        config_preview.add_service(new_service)
                        console.print(f"Added service: {new_service}", style=THEME["success_style"])
                    continue
                
                elif service_action == "Continue to Image Selection":
                    # Select the first service to configure
                    config_preview.set_current_service(service_names[0])
                    current_step = "select_service"
                
                elif service_action == "Go Back":
                    current_step = nav_stack.go_back()
                
                else:
                    # Configure a specific service
                    selected_service = service_action.replace("Configure Service: ", "")
                    config_preview.set_current_service(selected_service)
                    current_step = "select_service"
            
            elif current_step == "select_service":
                nav_stack.save_step(current_step)
                
                if len(service_names) > 1:
                    # Only show this step if there are multiple services
                    service_to_configure = questionary.select(
                        "Select service to configure:",
                        choices=service_names + ["Go Back"],
                        style=questionary_style
                    ).ask()
                    
                    if service_to_configure == "Go Back":
                        current_step = nav_stack.go_back()
                        continue
                    
                    config_preview.set_current_service(service_to_configure)
                
                # Display the current configuration
                config_preview.display_config()
                current_step = "base_image"
            
            elif current_step == "base_image":
                nav_stack.save_step(current_step)
                
                # Display current service being configured if in compose mode
                if config_type == "Docker Compose":
                    console.print(f"Configuring service: [bold]{config_preview.current_service}[/bold]", 
                                 style=THEME["info_style"])
                
                # Get base image
                selected_image = select_docker_image()
                
                if selected_image == "Go Back":
                    current_step = nav_stack.go_back()
                    continue
                elif not selected_image:
                    console.print("Base image selection canceled.", style=THEME["warning_style"])
                    return
                
                # Update the config preview with the selected image
                config_preview.update_base_image(selected_image)
                config_preview.display_config()
                
                current_step = "port_mapping"
            
            elif current_step == "port_mapping":
                nav_stack.save_step(current_step)
                
                # Display current service being configured if in compose mode
                if config_type == "Docker Compose":
                    console.print(f"Configuring service: [bold]{config_preview.current_service}[/bold]", 
                                 style=THEME["info_style"])
                
                add_port = questionary.confirm(
                    "Add port mapping?",
                    style=questionary_style
                ).ask()
                
                if add_port:
                    container_port = questionary.text(
                        "Container port:",
                        style=questionary_style
                    ).ask()
                    
                    host_port = questionary.text(
                        "Host port (default: same as container port):",
                        style=questionary_style
                    ).ask()
                    
                    if container_port:
                        if not host_port:
                            host_port = container_port
                        
                        config_preview.add_port(container_port, host_port)
                        config_preview.display_config()
                        
                        # Ask if user wants to add another port
                        add_another = questionary.confirm(
                            "Add another port mapping?",
                            style=questionary_style
                        ).ask()
                        
                        if add_another:
                            continue  # Stay on this step
                
                current_step = "volume_mapping"
            
            elif current_step == "volume_mapping":
                nav_stack.save_step(current_step)
                
                # Display current service being configured if in compose mode
                if config_type == "Docker Compose":
                    console.print(f"Configuring service: [bold]{config_preview.current_service}[/bold]", 
                                 style=THEME["info_style"])
                
                add_volume = questionary.confirm(
                    "Add volume mapping?",
                    style=questionary_style
                ).ask()
                
                if add_volume:
                    host_path = questionary.text(
                        "Host path:",
                        style=questionary_style
                    ).ask()
                    
                    container_path = questionary.text(
                        "Container path:",
                        style=questionary_style
                    ).ask()
                    
                    if host_path and container_path:
                        config_preview.add_volume(host_path, container_path)
                        config_preview.display_config()
                        
                        # Ask if user wants to add another volume
                        add_another = questionary.confirm(
                            "Add another volume mapping?",
                            style=questionary_style
                        ).ask()
                        
                        if add_another:
                            continue  # Stay on this step
                
                current_step = "environment_variables"
            
            elif current_step == "environment_variables":
                nav_stack.save_step(current_step)
                
                # Display current service being configured if in compose mode
                if config_type == "Docker Compose":
                    console.print(f"Configuring service: [bold]{config_preview.current_service}[/bold]", 
                                 style=THEME["info_style"])
                
                add_env = questionary.confirm(
                    "Add environment variable?",
                    style=questionary_style
                ).ask()
                
                if add_env:
                    env_key = questionary.text(
                        "Environment variable key:",
                        style=questionary_style
                    ).ask()
                    
                    env_value = questionary.text(
                        "Environment variable value:",
                        style=questionary_style
                    ).ask()
                    
                    if env_key:
                        config_preview.add_environment_variable(env_key, env_value)
                        config_preview.display_config()
                        
                        # Ask if user wants to add another environment variable
                        add_another = questionary.confirm(
                            "Add another environment variable?",
                            style=questionary_style
                        ).ask()
                        
                        if add_another:
                            continue  # Stay on this step
                
                current_step = "command"
            
            elif current_step == "command":
                nav_stack.save_step(current_step)
                
                # Display current service being configured if in compose mode
                if config_type == "Docker Compose":
                    console.print(f"Configuring service: [bold]{config_preview.current_service}[/bold]", 
                                 style=THEME["info_style"])
                
                add_command = questionary.confirm(
                    "Add command?",
                    style=questionary_style
                ).ask()
                
                if add_command:
                    command = questionary.text(
                        "Command:",
                        style=questionary_style
                    ).ask()
                    
                    if command:
                        config_preview.add_command(command)
                        config_preview.display_config()
                
                # For Docker Compose with multiple services
                if config_type == "Docker Compose" and len(service_names) > 1:
                    # Ask if user wants to configure another service
                    current_service_idx = service_names.index(config_preview.current_service)
                    
                    if current_service_idx < len(service_names) - 1:
                        next_service = questionary.confirm(
                            f"Configure next service ({service_names[current_service_idx + 1]})?",
                            style=questionary_style
                        ).ask()
                        
                        if next_service:
                            config_preview.set_current_service(service_names[current_service_idx + 1])
                            current_step = "base_image"
                            continue
                    
                    # Option to go back to a previous service
                    edit_service = questionary.confirm(
                        "Edit a different service?",
                        style=questionary_style
                    ).ask()
                    
                    if edit_service:
                        current_step = "select_service"
                        continue
                
                current_step = "review"
            
            elif current_step == "review":
                nav_stack.save_step(current_step)
                
                # Final review of the configuration
                console.print("[bold]Configuration Review:[/bold]", style=THEME["title_style"])
                config_preview.display_config()
                
                # Ask what to do with the configuration
                choices = [
                    "Save Configuration",
                    "Start Over",
                    "Go Back to Edit",
                    "Exit Without Saving"
                ]
                
                action = questionary.select(
                    "What would you like to do?",
                    choices=choices,
                    style=questionary_style
                ).ask()
                
                if action == "Save Configuration":
                    # Save the configuration to file
                    file_extension = ".dockerfile" if config_type == "Dockerfile" else ".yml"
                    filename = questionary.text(
                        f"Enter filename (will be saved with {file_extension} extension):",
                        style=questionary_style
                    ).ask()
                    
                    if not filename:
                        filename = "docker_config"
                    
                    if not filename.endswith(file_extension):
                        filename += file_extension
                    
                    try:
                        with open(filename, 'w') as f:
                            f.write(config_preview.get_config_as_string())
                        console.print(f"Configuration saved to {filename}", style=THEME["success_style"])
                        
                        # If this is a Docker Compose file, ask if user wants to create the containers
                        if config_type == "Docker Compose":
                            create_containers = questionary.confirm(
                                "Create containers from this configuration?",
                                style=questionary_style
                            ).ask()
                            
                            if create_containers:
                                run_command_with_spinner(f"docker-compose -f {filename} up -d", 
                                                        "Starting containers...")
                        
                        elif config_type == "Dockerfile" and container_name:
                            build_image = questionary.confirm(
                                "Build Docker image from this Dockerfile?",
                                style=questionary_style
                            ).ask()
                            
                            if build_image:
                                image_tag = questionary.text(
                                    "Enter image tag/name:",
                                    style=questionary_style
                                ).ask()
                                
                                if not image_tag:
                                    image_tag = container_name
                                
                                run_command_with_spinner(f"docker build -t {image_tag} -f {filename} .", 
                                                        "Building Docker image...")
                    except Exception as e:
                        console.print(f"Error saving configuration: {str(e)}", style=THEME["error_style"])
                    
                    return
                
                elif action == "Start Over":
                    console.print("Starting over...", style=THEME["warning_style"])
                    config_preview = None
                    config_type = None
                    container_name = ""
                    service_names = []
                    nav_stack = NavigationStack()  # Reset navigation
                    current_step = "config_type"
                
                elif action == "Go Back to Edit":
                    # Jump back to a previous step
                    edit_choices = ["Container/Service Type", "Base Image", "Port Mapping", 
                                   "Volume Mapping", "Environment Variables", "Command"]
                    
                    if config_type == "Docker Compose":
                        edit_choices.insert(1, "Service Setup")
                    elif config_type == "Dockerfile":
                        edit_choices.insert(1, "Container Name")
                    
                    edit_step = questionary.select(
                        "Which part would you like to edit?",
                        choices=edit_choices + ["Cancel"],
                        style=questionary_style
                    ).ask()
                    
                    if edit_step == "Cancel":
                        current_step = "review"  # Stay on review
                    elif edit_step == "Container/Service Type":
                        current_step = "config_type"
                    elif edit_step == "Container Name":
                        current_step = "container_name"
                    elif edit_step == "Service Setup":
                        current_step = "service_setup"
                    elif edit_step == "Base Image":
                        current_step = "base_image"
                    elif edit_step == "Port Mapping":
                        current_step = "port_mapping"
                    elif edit_step == "Volume Mapping":
                        current_step = "volume_mapping"
                    elif edit_step == "Environment Variables":
                        current_step = "environment_variables"
                    elif edit_step == "Command":
                        current_step = "command"
                
                else:  # Exit Without Saving
                    console.print("Exiting wizard without saving.", style=THEME["warning_style"])
                    return
        
        except KeyboardInterrupt:
            console.print("\nOperation canceled by user", style=THEME["warning_style"])
            return
        except Exception as e:
            console.print(f"Error: {str(e)}", style=THEME["error_style"])
            console.print("Press Enter to continue...")
            input()
            
    return

def display_keyboard_shortcuts():
    """Display a help panel with keyboard shortcuts"""
    shortcuts = [
        ("Ctrl+C", "Exit application"),
        ("Ctrl+B", "Go back to previous step"),
        ("Ctrl+F", "Go forward to next step"),
        ("Ctrl+H", "Show this help screen"),
        ("Ctrl+S", "Save current configuration"),
        ("Ctrl+R", "Refresh current view"),
        ("q or ESC", "Exit from monitor views safely")
    ]
    
    # Create a table for the shortcuts
    table = Table(title="Keyboard Shortcuts", box=THEME["border"])
    table.add_column("Shortcut", style="cyan")
    table.add_column("Description", style="green")
    
    for shortcut, description in shortcuts:
        table.add_row(shortcut, description)
    
    # Create a panel with the table
    panel = Panel(
        table,
        title="Keyboard Shortcuts Help",
        border_style=THEME["border_style"],
        padding=(1, 2)
    )
    
    console.print(panel)
    
    # Add additional note about monitor view
    console.print("\n[yellow]Note:[/] [cyan]When in Resource Monitor view, always use 'q' or ESC to exit safely.[/]")
    console.print("[cyan]Using Ctrl+C in the Resource Monitor will exit the entire application.[/]")
    
    # Wait for user to press Enter before returning
    console.print("\n[dim]Press Enter to continue...[/]", end="")
    input()

def start_container_from_image(container_name, image_name, wait=False):
    """
    Create and start a container with the given name from the specified image
    """
    # Create the container from the image
    console.print(f"[yellow]Creating container {container_name} from image {image_name}...[/]")
    create_args = ["create", "--name", container_name]
    create_args.append(image_name)
    
    returncode, stdout, stderr = run_command_with_spinner(
        "docker", create_args,
        f"Creating container {container_name} from image {image_name}..."
    )
    
    if returncode != 0:
        console.print(f"[bold red]FAILED[/] Failed to create container {container_name}")
        console.print(f"[red]{stderr}[/]")
        return
    
    console.print(f"[bold green]SUCCESS[/] Container {container_name} created successfully")
        
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

if __name__ == "__main__":
    # Register signal handler for clean exit
    def signal_handler(sig, frame):
        console.print("\n[yellow]Exiting...[/]")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the CLI
    app()