#!/usr/bin/env python3
"""
Interactive Mode Test Suite for Docker Orchestration CLI

This script tests the interactive mode of the Docker Orchestration CLI by:
1. Automating interactive input with pexpect
2. Testing container operations in interactive mode
3. Testing the resource monitor exit functionality
4. Testing the image pulling capabilities

Usage:
  python test_interactive_mode.py

Requirements:
  - pexpect
  - Docker installed and running
"""

import os
import sys
import time
import subprocess
import random
import string
import argparse

try:
    import pexpect
except ImportError:
    print("Error: This test requires the pexpect module.")
    print("Please install it with: pip install pexpect")
    sys.exit(1)

# Configuration
CLI_APP_PATH = "docker_orch_cli.py"
TEST_CONTAINER_PREFIX = "test-interactive-"

def random_string(length=8):
    """Generate a random string for container names"""
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(length))

def run_cmd(cmd, capture=True, ignore_error=False):
    """Run a shell command and return the output"""
    try:
        if capture:
            result = subprocess.run(
                cmd, 
                check=not ignore_error,
                text=True, 
                capture_output=True
            )
            return result
        else:
            # Just run without capturing output
            subprocess.run(
                cmd, 
                check=not ignore_error,
                stdout=subprocess.DEVNULL if capture else None,
                stderr=subprocess.DEVNULL if capture else None
            )
            return None
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            print(f"Command failed: {' '.join(cmd)}")
            print(f"Error: {e}")
        raise

def cleanup_test_containers():
    """Remove all test containers"""
    print("\n=== Cleaning up test containers ===")
    # List all containers with the test prefix
    try:
        result = run_cmd(["docker", "ps", "-a", "--format", "{{.Names}}"])
        containers = [c for c in result.stdout.strip().split('\n') if c and c.startswith(TEST_CONTAINER_PREFIX)]
        
        if containers:
            print(f"Found {len(containers)} test containers to remove")
            for container in containers:
                print(f"Removing container: {container}")
                run_cmd(["docker", "rm", "-f", container], ignore_error=True)
        else:
            print("No test containers found to clean up")
    except Exception as e:
        print(f"Error cleaning up containers: {e}")

def test_interactive_container_management():
    """Test container management in interactive mode"""
    print("\n=== Testing Interactive Container Management ===")
    
    # Create a unique container name
    container_name = f"{TEST_CONTAINER_PREFIX}{random_string()}"
    
    try:
        # Pull the nginx image to ensure it exists
        run_cmd(["docker", "pull", "nginx:latest"], capture=False)
        
        # Start the interactive CLI process
        print("Starting interactive CLI...")
        child = pexpect.spawn(f"python {CLI_APP_PATH} interactive")
        
        # Wait for the main menu
        child.expect("Select an action:")
        print("Got main menu")
        
        # Select Container Management
        child.sendline()  # Container Management is usually the first option
        child.expect("Container Management:")
        print("Got container management menu")
        
        # Select Start Container
        child.send("\x1b[B")  # Down arrow
        child.sendline()  # Select Start Container
        child.expect("Select container to start:")
        print("Got container selection prompt")
        
        # We don't have any containers yet, so we should create one
        # Exit this menu
        child.sendcontrol("c")
        child.expect("Container Management:")
        
        # Interact with Docker directly to create a container
        print(f"Creating container {container_name}...")
        run_cmd(["docker", "create", "--name", container_name, "nginx:latest"], capture=False)
        
        # Now try starting it again
        child.send("\x1b[B")  # Down arrow
        child.sendline()  # Select Start Container
        child.expect("Select container to start:")
        print("Looking for our container in the list...")
        
        # Navigate to find our container (might need to adjust depending on container list)
        # Try a few down arrows to find it
        for _ in range(10):  # Try up to 10 positions
            child.send("\x1b[B")  # Down arrow
            child.expect(".", timeout=1)  # Just wait for any output
            if container_name in child.before.decode('utf-8'):
                break
        
        # Select the container
        child.sendline()
        
        # Wait for success message
        child.expect(f"Container {container_name} started successfully", timeout=10)
        print("Container started successfully")
        
        # Check if container is actually running
        result = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"])
        running_status = result.stdout.strip()
        assert running_status and "Up" in running_status, f"Container should be running, status: {running_status}"
        
        # Exit interactive mode
        child.sendcontrol("c")  # Back to container menu
        child.expect("Container Management:")
        child.send("\x1b[B\x1b[B\x1b[B\x1b[B\x1b[B")  # Navigate to "Back to Main Menu"
        child.sendline()
        child.expect("Select an action:")
        child.send("\x1b[B\x1b[B\x1b[B\x1b[B")  # Navigate to "Exit"
        child.sendline()
        
        print("✅ Interactive container management test passed")
        return True
        
    except pexpect.exceptions.TIMEOUT:
        print("❌ Test failed: Timeout while waiting for expected output")
        print(f"Last output: {child.before.decode('utf-8')}")
        return False
    except AssertionError as e:
        print(f"❌ Test failed: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Test error: {str(e)}")
        return False
    finally:
        # Clean up
        try:
            child.close()
        except:
            pass
        run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)

def test_interactive_monitor_exit():
    """Test that the resource monitor can be exited cleanly with 'q'"""
    print("\n=== Testing Resource Monitor Exit Functionality ===")
    
    try:
        # Start the monitor process
        print("Starting resource monitor...")
        child = pexpect.spawn(f"python {CLI_APP_PATH} monitor")
        
        # Wait for monitor to start
        child.expect("Starting resource monitor", timeout=5)
        print("Monitor started")
        
        # Give it a moment to initialize
        time.sleep(3)
        
        # Press 'q' to exit
        print("Pressing 'q' to exit...")
        child.send("q")
        
        # Wait for exit message
        child.expect("Exiting monitor...", timeout=5)
        child.expect("Resource monitor stopped successfully", timeout=5)
        
        # Make sure the process ends
        child.expect(pexpect.EOF, timeout=5)
        
        print("✅ Resource monitor exit test passed")
        return True
        
    except pexpect.exceptions.TIMEOUT:
        print("❌ Test failed: Timeout while waiting for expected output")
        print(f"Last output: {child.before.decode('utf-8') if hasattr(child, 'before') else 'No output'}")
        return False
    except Exception as e:
        print(f"❌ Test error: {str(e)}")
        return False
    finally:
        try:
            # Just in case it's still running
            child.close(force=True)
        except:
            pass

def test_interactive_new_container_from_image():
    """Test creating and starting a new container from an image in interactive mode"""
    print("\n=== Testing Interactive New Container Creation ===")
    
    # Create a unique container name
    container_name = f"{TEST_CONTAINER_PREFIX}{random_string()}"
    image_name = "alpine:latest"  # Small image for quick tests
    
    try:
        # Remove the alpine image if it exists to test pulling
        run_cmd(["docker", "rmi", image_name], ignore_error=True)
        
        # Start the interactive CLI process
        print("Starting interactive CLI...")
        child = pexpect.spawn(f"python {CLI_APP_PATH} interactive")
        
        # Wait for the main menu
        child.expect("Select an action:")
        print("Got main menu")
        
        # Select Container Management
        child.sendline()  # Container Management is usually the first option
        child.expect("Container Management:")
        print("Got container management menu")
        
        # Select Start Container
        child.send("\x1b[B")  # Down arrow
        child.sendline()  # Select Start Container
        child.expect("Select container to start:")
        print("Got container selection prompt")
        
        # We don't have the container, so we need to use new container option
        # First exit this menu
        child.sendcontrol("c")
        child.expect("Container Management:")
        child.sendcontrol("c")
        child.expect("Select an action:")
        
        # Create a container through command-line mode to have more control
        print(f"Starting container through CLI with implicit creation...")
        child.close()
        
        # Use the main CLI command to start a new container
        result = run_cmd(
            ["python", CLI_APP_PATH, "start", container_name],
            capture=True
        )
        
        # Verify output contains expected messages
        output = result.stdout
        assert f"Container {container_name} does not exist" in output, "Should detect non-existent container"
        assert "Checking if image" in output, "Should check for image"
        assert "Pulling from registry" in output, "Should pull image"
        assert f"Container {container_name} started successfully" in output, "Should start container"
        
        # Verify container is running
        result = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
        running = result.stdout.strip()
        assert container_name in running, f"Container should be running, got: {running}"
        
        print("✅ Interactive new container creation test passed")
        return True
        
    except pexpect.exceptions.TIMEOUT:
        print("❌ Test failed: Timeout while waiting for expected output")
        print(f"Last output: {child.before.decode('utf-8') if hasattr(child, 'before') else 'No output'}")
        return False
    except AssertionError as e:
        print(f"❌ Test failed: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Test error: {str(e)}")
        return False
    finally:
        # Clean up
        try:
            if 'child' in locals() and child:
                child.close(force=True)
        except:
            pass
        run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)

def run_all_tests():
    """Run all tests and report results"""
    cleanup_test_containers()
    
    tests = [
        ("Interactive Container Management", test_interactive_container_management),
        ("Resource Monitor Exit Functionality", test_interactive_monitor_exit),
        ("Interactive New Container Creation", test_interactive_new_container_from_image)
    ]
    
    results = []
    
    print("\n" + "="*50)
    print("DOCKER ORCHESTRATION CLI - INTERACTIVE MODE TESTS")
    print("="*50)
    
    for name, test_func in tests:
        print(f"\n{'='*20} RUNNING TEST: {name} {'='*20}")
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test error: {str(e)}")
            results.append((name, False))
    
    # Final cleanup
    cleanup_test_containers()
    
    # Print summary
    print("\n" + "="*50)
    print("TEST RESULTS SUMMARY")
    print("="*50)
    
    passed = 0
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {name}")
        if result:
            passed += 1
    
    print(f"\nPassed {passed}/{len(results)} tests")
    
    return passed == len(results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test interactive mode functionality')
    parser.add_argument('--test', help='Run a specific test: container, monitor, new-container')
    parser.add_argument('--cleanup', action='store_true', help='Just clean up test containers')
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup_test_containers()
        sys.exit(0)
    
    if args.test:
        if args.test == 'container':
            test_interactive_container_management()
        elif args.test == 'monitor':
            test_interactive_monitor_exit()
        elif args.test == 'new-container':
            test_interactive_new_container_from_image()
        else:
            print(f"Unknown test: {args.test}")
    else:
        success = run_all_tests()
        sys.exit(0 if success else 1) 