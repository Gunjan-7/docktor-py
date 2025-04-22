# Docker Orchestration CLI Test Suite

This directory contains a comprehensive test suite for the Docker Orchestration CLI application.

## Overview

The tests cover both command-line mode and interactive mode functionality, with a focus on:

1. Container management operations (start, stop, restart, logs)
2. Image pulling capabilities
3. Resource monitor functionality
4. API interaction

## Test Files

- `test_docker_orch_cli.py`: Comprehensive unit and integration tests
- `test_container_start.py`: Focused tests for container start functionality
- `test_interactive_mode.py`: Tests for interactive mode using pexpect

## Requirements

- Python 3.6+
- Docker installed and running
- Required Python packages:
  - pytest
  - pytest-mock
  - pytest-timeout
  - pexpect (for interactive tests)

```bash
pip install pytest pytest-mock pytest-timeout pexpect
```

## Running the Tests

### All Tests

To run all tests:

```bash
# Run the complete test suite
python test_docker_orch_cli.py

# Run specific test scripts
python test_container_start.py
python test_interactive_mode.py
```

### Specific Tests

#### Container Start Functionality Tests

```bash
# Run all container start tests
python test_container_start.py

# Run specific container start tests
python test_container_start.py --test existing         # Test starting existing containers
python test_container_start.py --test new-existing     # Test creating containers from existing images
python test_container_start.py --test new-nonexisting  # Test pulling and creating containers
python test_container_start.py --test multi            # Test with multiple image types
```

#### Interactive Mode Tests

```bash
# Run all interactive mode tests
python test_interactive_mode.py

# Run specific interactive tests
python test_interactive_mode.py --test container     # Test container management in interactive mode
python test_interactive_mode.py --test monitor       # Test resource monitor exit functionality
python test_interactive_mode.py --test new-container # Test creating new containers interactively
```

### Cleaning Up Test Containers

All test scripts include cleanup functionality. However, if you need to clean up manually:

```bash
python test_container_start.py --cleanup
python test_interactive_mode.py --cleanup
```

## Test Coverage

### Command-Line Mode Tests

1. **Container Management**
   - Starting existing containers
   - Creating and starting containers from existing images
   - Pulling, creating, and starting containers from non-existent images
   - Stopping containers
   - Restarting containers
   - Viewing container logs

2. **Edge Cases**
   - Handling non-existent images
   - Error handling and reporting
   - Fall-back behavior when API is unavailable

### Interactive Mode Tests

1. **Container Operations**
   - Navigating the interactive menus
   - Starting containers in interactive mode
   - Creating new containers interactively

2. **Resource Monitor**
   - Starting the resource monitor
   - Exiting the monitor with the 'q' key
   - Verifying clean shutdown

### API Interaction Tests

1. **API Requests**
   - Successful API requests
   - Handling API failures
   - Fallback to direct Docker CLI

## Container Start Functionality

The container start functionality has been enhanced to work in these scenarios:

1. **Existing Container**: If the container exists locally, it will be started directly.

2. **Non-existent Container, Existing Image**: If the container doesn't exist but an image with the same name exists, it will:
   - Create a new container from the image
   - Start the container

3. **Non-existent Container, Non-existent Image**: If neither the container nor image exist locally, it will:
   - Pull the image from a registry
   - Create a new container
   - Start the container

This automated workflow eliminates the need for separate pull/create/start commands.

## Troubleshooting

If you encounter issues with tests:

1. Ensure Docker is running and your user has permissions to use it
2. Check for leftover test containers with `docker ps -a | grep test-`
3. Check Docker image availability with `docker images`
4. For pexpect timeouts, try increasing timeout values in the tests
5. Clear Docker caches if disk space is an issue: `docker system prune` 