# Docker Orchestration System

A comprehensive Python application to manage Docker containers with advanced scheduling and resource allocation capabilities.

## Features

- **Resource Management**: Allocate CPU, memory, and other resources based on container priority
- **Task Scheduling**: Schedule container tasks based on priority and resource requirements
- **Container Checkpointing**: Pause and resume containers with state preservation
- **API Server**: RESTful API for managing containers and tasks
- **Modern CLI**: Interactive command-line interface with rich UI

## Project Structure

```
docker-orcha/
├── docker_orcha/              # Main package
│   ├── api/                   # API server
│   │   ├── routes.py          # API routes
│   │   └── server.py          # API server
│   ├── cli/                   # CLI interface
│   │   ├── commands.py        # CLI commands
│   │   └── interactive.py     # Interactive CLI
│   ├── core/                  # Core functionality
│   │   ├── docker_manager.py  # Docker management
│   │   └── scheduler.py       # Task scheduling
│   ├── models/                # Data models
│   │   ├── enums.py           # Enum definitions
│   │   ├── resources.py       # Resource models
│   │   └── task.py            # Task model
│   └── utils/                 # Utilities
│       ├── docker_utils.py    # Docker utilities
│       └── formatting.py      # Formatting utilities
├── docker_orcha_api.py        # API server entry point
├── docker_orcha_cli.py        # CLI entry point
└── requirements.txt           # Dependencies
```

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/docker-orcha.git
   cd docker-orcha
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### API Server

Start the API server:

```
python docker_orcha_api.py --host 0.0.0.0 --port 5000
```

Options:
- `--host`: Host to bind to (default: 0.0.0.0)
- `--port`: Port to bind to (default: 5000)
- `--debug`: Enable debug mode
- `--state-dir`: Directory to store state (default: ./container_states)

### CLI

The CLI provides several commands for managing Docker containers and tasks:

```
python docker_orcha_cli.py --help
```

#### Interactive Mode

For a more user-friendly experience, use the interactive mode:

```
python docker_orcha_cli.py interactive
```

The interactive mode provides a menu-driven interface for:
- Container management (listing, viewing logs, stopping, restarting)
- Task management (creating, starting, stopping, resuming, deleting)
- System management (viewing status, rebalancing resources, managing scheduler)

#### CLI Examples

- Show system status:
  ```
  python docker_orcha_cli.py system status
  ```

- List containers:
  ```
  python docker_orcha_cli.py container list
  ```

- List tasks:
  ```
  python docker_orcha_cli.py task list
  ```

## API Endpoints

- `GET /api/tasks`: List all tasks
- `POST /api/tasks`: Create a new task
- `GET /api/tasks/<task_id>`: Get task details
- `PUT /api/tasks/<task_id>`: Update task
- `DELETE /api/tasks/<task_id>`: Delete task
- `POST /api/tasks/<task_id>/start`: Start task
- `POST /api/tasks/<task_id>/stop`: Stop task
- `POST /api/tasks/<task_id>/resume`: Resume task
- `GET /api/containers`: List containers
- `GET /api/containers/<container_id>/logs`: Get container logs
- `GET /api/system/status`: Get system status
- `POST /api/system/rebalance`: Rebalance resources
- `POST /api/scheduler/start`: Start scheduler
- `POST /api/scheduler/stop`: Stop scheduler

## License

This project is licensed under the MIT License - see the LICENSE file for details. 