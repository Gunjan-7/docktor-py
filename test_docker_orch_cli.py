#!/usr/bin/env python3
"""
Test Suite for Docker Orchestration CLI

This suite tests both the interactive and command-line modes of the Docker Orchestration CLI application.
It covers container management, resource monitoring, and API interaction functionalities.

Usage:
  python test_docker_orch_cli.py

Requirements:
  - pytest
  - pytest-mock
  - pytest-timeout
  - unittest.mock
"""

import os
import sys
import time
import json
import unittest
import subprocess
import pytest
from unittest.mock import patch, MagicMock, call
from io import StringIO

# Constants for testing
TEST_CONTAINER_NAME = "test-nginx"
TEST_IMAGE_NAME = "nginx:latest"
TEST_TASK_ID = "task_12345"
TEST_API_URL = "http://localhost:5000/api"

# Path to the CLI app
CLI_APP_PATH = "docker_orch_cli.py"

class TestDockerOrchCLI(unittest.TestCase):
    """Test cases for Docker Orchestration CLI"""

    def setUp(self):
        """Set up test environment"""
        # Clean up any test containers from previous test runs
        try:
            subprocess.run(["docker", "rm", "-f", TEST_CONTAINER_NAME], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def tearDown(self):
        """Clean up after tests"""
        # Remove test containers
        try:
            subprocess.run(["docker", "rm", "-f", TEST_CONTAINER_NAME], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @pytest.mark.timeout(20)
    def test_command_line_container_start_with_nonexistent_image(self):
        """Test starting a container with a non-existent image name"""
        # Use a unique name for test
        unique_name = f"nonexistent-{int(time.time())}"
        
        # Test the command with a non-existent image
        result = subprocess.run(
            ["python", CLI_APP_PATH, "start", unique_name],
            text=True,
            capture_output=True
        )
        
        # Check that it attempted to create from image
        self.assertIn(f"Container {unique_name} does not exist", result.stdout)
        self.assertIn("Pulling from registry", result.stdout)
        self.assertIn("Failed to pull image", result.stdout)

    @pytest.mark.timeout(30)
    def test_command_line_container_start_with_existing_image(self):
        """Test starting a container using an existing image"""
        # First ensure nginx image exists locally
        subprocess.run(
            ["docker", "pull", "nginx:latest"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Test starting a container with that image
        result = subprocess.run(
            ["python", CLI_APP_PATH, "start", "test-nginx"],
            text=True,
            capture_output=True
        )
        
        # Check outputs
        self.assertIn("test-nginx does not exist", result.stdout)
        self.assertIn("Checking if image test-nginx exists locally", result.stdout)
        
        # Check if it created and started the container
        container_check = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=test-nginx"],
            text=True,
            capture_output=True
        )
        
        self.assertIn("test-nginx", container_check.stdout)

    @pytest.mark.timeout(20)
    def test_command_line_container_logs(self):
        """Test viewing container logs"""
        # Ensure the container exists
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", TEST_CONTAINER_NAME, TEST_IMAGE_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Give container time to produce logs
            time.sleep(2)
            
            # Test logs command
            result = subprocess.run(
                ["python", CLI_APP_PATH, "logs", TEST_CONTAINER_NAME, "--tail", "5"],
                text=True,
                capture_output=True
            )
            
            # Verify logs were fetched
            self.assertIn("Fetching logs", result.stdout)
            
        except Exception as e:
            self.fail(f"Failed to set up test container: {str(e)}")

    @pytest.mark.timeout(20)
    def test_command_line_container_stop(self):
        """Test stopping a container"""
        # Ensure the container exists and is running
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", TEST_CONTAINER_NAME, TEST_IMAGE_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Test stop command
            result = subprocess.run(
                ["python", CLI_APP_PATH, "stop", TEST_CONTAINER_NAME],
                text=True,
                capture_output=True
            )
            
            # Verify container was stopped
            self.assertIn("Stopping container", result.stdout)
            
            # Check container status
            status = subprocess.run(
                ["docker", "container", "inspect", "-f", "{{.State.Status}}", TEST_CONTAINER_NAME],
                text=True,
                capture_output=True
            )
            
            self.assertEqual(status.stdout.strip(), "exited")
            
        except Exception as e:
            self.fail(f"Failed to set up test container: {str(e)}")

    @pytest.mark.timeout(20)
    def test_command_line_container_restart(self):
        """Test restarting a container"""
        # Ensure the container exists and is running
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", TEST_CONTAINER_NAME, TEST_IMAGE_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Stop the container first
            subprocess.run(
                ["docker", "stop", TEST_CONTAINER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Test restart command
            result = subprocess.run(
                ["python", CLI_APP_PATH, "restart", TEST_CONTAINER_NAME],
                text=True,
                capture_output=True
            )
            
            # Verify container was restarted
            self.assertIn("Restarting container", result.stdout)
            
            # Check container status
            status = subprocess.run(
                ["docker", "container", "inspect", "-f", "{{.State.Status}}", TEST_CONTAINER_NAME],
                text=True,
                capture_output=True
            )
            
            self.assertEqual(status.stdout.strip(), "running")
            
        except Exception as e:
            self.fail(f"Failed to set up test container: {str(e)}")

    # API interaction tests
    @patch('requests.get')
    def test_api_request_success(self, mock_get):
        """Test successful API request"""
        # Import the module specifically for this test
        sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
        from docker_orch_cli import api_request
        
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        # Test the function
        result = api_request("system/status")
        
        # Verify the result
        self.assertEqual(result, {"status": "ok"})
        mock_get.assert_called_once_with(f"{TEST_API_URL}/system/status", timeout=2)

    @patch('requests.get')
    def test_api_request_failure(self, mock_get):
        """Test API request failure"""
        # Import the module specifically for this test
        sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
        from docker_orch_cli import api_request
        
        # Mock the response to raise an exception
        mock_get.side_effect = Exception("Connection failed")
        
        # Test the function
        result = api_request("system/status")
        
        # Verify the result includes error flag
        self.assertIn("error", result)
        self.assertIn("api_unavailable", result)

# Interactive mode tests using mock inputs
class TestInteractiveMode(unittest.TestCase):
    """Test cases for interactive mode using mocked inputs"""
    
    @patch('questionary.select')
    @patch('docker_orch_cli.run_command_with_spinner')
    def test_interactive_container_start(self, mock_run_command, mock_select):
        """Test interactive container start"""
        # Setup mocks
        mock_select.return_value.ask.return_value = "Existing container"
        mock_select_containers = MagicMock(return_value="test-container")
        
        # Mock command responses
        mock_run_command.return_value = (0, "container started", "")
        
        # Import after mocking
        with patch('docker_orch_cli.select_containers', mock_select_containers):
            with patch('docker_orch_cli.console.print') as mock_print:
                sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
                from docker_orch_cli import container_submenu
                
                # Call container submenu
                with patch('builtins.input', return_value=""):
                    try:
                        container_submenu()
                    except StopIteration:
                        # This is expected when mock input is exhausted
                        pass
                
                # Check that the right functions were called
                mock_select.assert_called()
                mock_select_containers.assert_called()
                mock_run_command.assert_called()
                
                # Check that success message was printed
                mock_print.assert_any_call("[bold green]✓[/] Container test-container started successfully")

    @patch('docker_orch_cli.api_request')
    def test_system_status_api(self, mock_api_request):
        """Test system status with API"""
        # Setup mock API response
        mock_api_request.return_value = {
            "docker_version": "20.10.12",
            "containers_running": 2,
            "containers_paused": 0,
            "containers_stopped": 3,
            "images": 10,
            "task_counts": {
                "pending": 1,
                "running": 2,
                "paused": 0,
                "completed": 5,
                "failed": 1
            }
        }
        
        # Import after mocking
        with patch('docker_orch_cli.console.print') as mock_print:
            with patch('docker_orch_cli.console.status', MagicMock()):
                sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
                from docker_orch_cli import system_status
                
                # Call system status
                system_status()
                
                # Verify API was called correctly
                mock_api_request.assert_called_with("system/status")
                
                # Check that output contains relevant information
                # Note: Since Rich console output is complex, we just check for key calls
                calls = [call for call in mock_print.call_args_list if isinstance(call.args[0], str)]
                has_system_info = any("System Information" in str(arg) for call in mock_print.call_args_list for arg in call.args)
                self.assertTrue(has_system_info)

class TestResourceMonitor(unittest.TestCase):
    """Test the resource monitor functionality"""
    
    @patch('threading.Thread')
    def test_resource_monitor_start_stop(self, mock_thread):
        """Test starting and stopping the resource monitor"""
        # Import modules
        sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
        from docker_orch_cli import ResourceMonitor
        
        # Create monitor instance
        monitor = ResourceMonitor()
        
        # Test start
        monitor.start()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        self.assertTrue(monitor.running)
        
        # Test stop
        monitor.stop()
        self.assertFalse(monitor.running)
        mock_thread.return_value.join.assert_called_once()

# Command execution utilities tests
class TestCommandUtils(unittest.TestCase):
    """Test command execution utilities"""
    
    @patch('subprocess.run')
    def test_run_command_with_spinner(self, mock_run):
        """Test running commands with spinner"""
        # Setup mock
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "Command output"
        mock_process.stderr = ""
        mock_run.return_value = mock_process
        
        # Import function
        sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
        from docker_orch_cli import run_command_with_spinner
        
        # Run test
        returncode, stdout, stderr = run_command_with_spinner("docker", ["ps"], "Listing containers")
        
        # Verify results
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, "Command output")
        self.assertEqual(stderr, "")
        mock_run.assert_called_with(
            ["docker", "ps"],
            text=True,
            capture_output=True
        )

    @patch('subprocess.Popen')
    def test_run_command_with_live_output(self, mock_popen):
        """Test running commands with live output"""
        # Setup mock
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["Line 1\n", "Line 2\n", ""]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        # Import function
        sys.path.append(os.path.dirname(os.path.abspath(CLI_APP_PATH)))
        with patch('docker_orch_cli.console.print') as mock_print:
            from docker_orch_cli import run_command_with_live_output
            
            # Run test
            returncode = run_command_with_live_output("docker", ["logs", "container"])
            
            # Verify results
            self.assertEqual(returncode, 0)
            mock_popen.assert_called_with(
                ["docker", "logs", "container"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            mock_print.assert_any_call("Line 1\n", end="")
            mock_print.assert_any_call("Line 2\n", end="")

# End-to-end CLI commands test
@pytest.mark.integration
class TestCLICommandsE2E(unittest.TestCase):
    """End-to-end tests for CLI commands"""
    
    def setUp(self):
        """Set up test environment"""
        # Clean up test containers
        try:
            subprocess.run(["docker", "rm", "-f", TEST_CONTAINER_NAME], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass
            
        # Pull test image
        try:
            subprocess.run(["docker", "pull", TEST_IMAGE_NAME], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def tearDown(self):
        """Clean up after tests"""
        # Remove test containers
        try:
            subprocess.run(["docker", "rm", "-f", TEST_CONTAINER_NAME], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @pytest.mark.timeout(30)
    def test_e2e_container_lifecycle(self):
        """Test full container lifecycle: start -> logs -> stop"""
        # 1. Start a container
        start_result = subprocess.run(
            ["python", CLI_APP_PATH, "start", TEST_CONTAINER_NAME],
            text=True,
            capture_output=True
        )
        
        # Verify container started
        self.assertTrue(
            "Container test-nginx does not exist" in start_result.stdout or
            "Container test-nginx started successfully" in start_result.stdout
        )
        
        # Verify container is running
        ps_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={TEST_CONTAINER_NAME}", "--format", "{{.Names}}"],
            text=True,
            capture_output=True
        )
        self.assertIn(TEST_CONTAINER_NAME, ps_result.stdout)
        
        # 2. Get container logs
        logs_result = subprocess.run(
            ["python", CLI_APP_PATH, "logs", TEST_CONTAINER_NAME, "--tail", "5"],
            text=True,
            capture_output=True
        )
        
        # Verify logs were fetched
        self.assertIn("Fetching logs", logs_result.stdout)
        
        # 3. Stop the container
        stop_result = subprocess.run(
            ["python", CLI_APP_PATH, "stop", TEST_CONTAINER_NAME],
            text=True,
            capture_output=True
        )
        
        # Verify container was stopped
        self.assertIn("Stopping container", stop_result.stdout)
        
        # Check container status
        status = subprocess.run(
            ["docker", "container", "inspect", "-f", "{{.State.Status}}", TEST_CONTAINER_NAME],
            text=True,
            capture_output=True
        )
        
        self.assertEqual(status.stdout.strip(), "exited")

    @pytest.mark.timeout(20)
    def test_e2e_container_restart(self):
        """Test container restart capability"""
        # 1. Start a container
        subprocess.run(
            ["python", CLI_APP_PATH, "start", TEST_CONTAINER_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # 2. Stop it first
        subprocess.run(
            ["docker", "stop", TEST_CONTAINER_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # 3. Restart it
        restart_result = subprocess.run(
            ["python", CLI_APP_PATH, "restart", TEST_CONTAINER_NAME],
            text=True,
            capture_output=True
        )
        
        # Verify restart message
        self.assertIn("Starting container", restart_result.stdout)
        
        # Check container status
        status = subprocess.run(
            ["docker", "container", "inspect", "-f", "{{.State.Status}}", TEST_CONTAINER_NAME],
            text=True,
            capture_output=True
        )
        
        self.assertEqual(status.stdout.strip(), "running")

if __name__ == "__main__":
    # Run tests
    unittest.main() 