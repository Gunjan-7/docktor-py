#!/usr/bin/env python3
"""
Container Start Functionality Test Suite

This script tests the Docker Orchestration CLI's container start functionality,
focusing specifically on its ability to:
1. Start existing containers
2. Create and start new containers from existing images
3. Pull and start containers with non-existent images
4. Test both interactive and command-line modes

Usage:
  python test_container_start.py
"""

import os
import sys
import time
import subprocess
import argparse
import random
import string

# Configuration
CLI_APP_PATH = "docker_orch_cli.py"
TEST_IMAGES = [
    "nginx:latest",           # Common web server
    "redis:latest",           # Common caching server  
    "python:3.9-slim",        # Slim Python image
    "alpine:latest",          # Tiny Linux distro
    "busybox:latest"          # Minimal Linux utilities
]

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
            print(f"Output: {e.stdout}")
            print(f"Error output: {e.stderr}")
        raise

def cleanup_test_containers(prefix="test-"):
    """Remove all test containers"""
    print("\n=== Cleaning up test containers ===")
    # List all containers with the test prefix
    try:
        result = run_cmd(["docker", "ps", "-a", "--format", "{{.Names}}"])
        containers = [c for c in result.stdout.strip().split('\n') if c and c.startswith(prefix)]
        
        if containers:
            print(f"Found {len(containers)} test containers to remove")
            for container in containers:
                print(f"Removing container: {container}")
                run_cmd(["docker", "rm", "-f", container], ignore_error=True)
        else:
            print("No test containers found to clean up")
    except Exception as e:
        print(f"Error cleaning up containers: {e}")

def test_start_existing_container():
    """Test starting an existing container that's stopped"""
    print("\n=== Test Starting Existing Container ===")
    
    # Create a container name
    container_name = f"test-existing-{random_string()}"
    
    try:
        # Create but don't start a container
        print(f"Creating container {container_name}...")
        run_cmd(
            ["docker", "create", "--name", container_name, "nginx:latest"],
            capture=False
        )
        
        # Verify it exists but is not running
        result = run_cmd(["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Status}}"])
        status = result.stdout.strip()
        print(f"Container initial status: {status}")
        assert "Created" in status, f"Expected container to be in 'Created' state, got: {status}"
        
        # Start the container using our CLI
        print(f"Starting container {container_name} using CLI...")
        result = run_cmd(["python", CLI_APP_PATH, "start", container_name])
        output = result.stdout
        
        # Check output
        print("Checking CLI output...")
        assert f"Starting container {container_name}" in output, "Missing starting message in output"
        assert f"Container {container_name} started successfully" in output, "Missing success message in output"
        
        # Verify it's running now
        result = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"])
        running_status = result.stdout.strip()
        print(f"Container final status: {running_status}")
        assert running_status and "Up" in running_status, f"Container should be running, status: {running_status}"
        
        print("✅ Test passed: Container started successfully")
        return True
        
    except AssertionError as e:
        print(f"❌ Test failed: {str(e)}")
        return False
    finally:
        # Clean up
        run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)

def test_start_nonexistent_container_existing_image():
    """Test starting a non-existent container with an existing image"""
    print("\n=== Test Starting Non-existent Container (Existing Image) ===")
    
    # Create a unique container name
    container_name = f"test-nonexisting-{random_string()}"
    image_name = "nginx:latest"
    
    try:
        # Make sure the image exists locally
        print(f"Ensuring image {image_name} exists locally...")
        run_cmd(["docker", "pull", image_name], capture=False)
        
        # Start the non-existent container using our CLI
        print(f"Starting non-existent container {container_name}...")
        result = run_cmd(["python", CLI_APP_PATH, "start", container_name])
        output = result.stdout
        
        # Check output
        print("Checking CLI output...")
        assert f"Container {container_name} does not exist" in output, "Missing container not exist message"
        assert f"Creating container {container_name}" in output, "Missing container creation message"
        assert f"Container {container_name} started successfully" in output, "Missing success message in output"
        
        # Verify it's running now
        result = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
        running = result.stdout.strip()
        print(f"Running container name: {running}")
        assert container_name in running, f"Container should be running, got: {running}"
        
        print("✅ Test passed: Non-existent container created and started successfully")
        return True
        
    except AssertionError as e:
        print(f"❌ Test failed: {str(e)}")
        return False
    finally:
        # Clean up
        run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)

def test_start_nonexistent_container_nonexistent_image():
    """Test starting a non-existent container with a non-existent image that needs pulling"""
    print("\n=== Test Starting Non-existent Container (Non-existent Image) ===")
    
    # Create a unique container name
    container_name = f"test-nonexisting-{random_string()}"
    image_name = "alpine:latest"  # Small image for quick download
    
    try:
        # Make sure the image doesn't exist locally
        print(f"Removing image {image_name} if it exists...")
        run_cmd(["docker", "rmi", image_name], ignore_error=True)
        
        # Start the non-existent container using our CLI
        print(f"Starting non-existent container {container_name}...")
        result = run_cmd(["python", CLI_APP_PATH, "start", container_name])
        output = result.stdout
        
        # Check output
        print("Checking CLI output...")
        assert f"Container {container_name} does not exist" in output, "Missing container not exist message"
        assert "Pulling from registry" in output, "Missing pulling message"
        assert "pulled successfully" in output, "Missing pull success message"
        assert f"Container {container_name} started successfully" in output, "Missing success message in output"
        
        # Verify it's running now
        result = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
        running = result.stdout.strip()
        print(f"Running container name: {running}")
        assert container_name in running, f"Container should be running, got: {running}"
        
        print("✅ Test passed: Non-existent container created from pulled image and started successfully")
        return True
        
    except AssertionError as e:
        print(f"❌ Test failed: {str(e)}")
        return False
    finally:
        # Clean up
        run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)

def test_all_images():
    """Test starting containers with all test images"""
    print("\n=== Testing Multiple Image Types ===")
    results = []
    
    for image in TEST_IMAGES:
        print(f"\n--- Testing with image: {image} ---")
        container_name = f"test-multi-{random_string()}"
        
        try:
            # Remove image to force pulling
            run_cmd(["docker", "rmi", image], ignore_error=True)
            
            # Start container with image name
            result = run_cmd(["python", CLI_APP_PATH, "start", container_name])
            
            # Check if container is running
            running = run_cmd(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
            if container_name in running.stdout:
                print(f"✅ Successfully created and started container with {image}")
                results.append((image, True))
            else:
                print(f"❌ Failed to create container with {image}")
                results.append((image, False))
                
        except Exception as e:
            print(f"❌ Error with {image}: {str(e)}")
            results.append((image, False))
        finally:
            # Clean up
            run_cmd(["docker", "rm", "-f", container_name], ignore_error=True)
    
    # Print summary
    print("\n=== Image Test Summary ===")
    for image, success in results:
        print(f"{'✅' if success else '❌'} {image}")
    
    return all(success for _, success in results)

def run_all_tests():
    """Run all tests and report results"""
    cleanup_test_containers()
    
    tests = [
        ("Start Existing Container", test_start_existing_container),
        ("Start Non-existent Container (Existing Image)", test_start_nonexistent_container_existing_image),
        ("Start Non-existent Container (Non-existent Image)", test_start_nonexistent_container_nonexistent_image),
        ("Multiple Image Types", test_all_images)
    ]
    
    results = []
    
    print("\n" + "="*50)
    print("DOCKER ORCHESTRATION CLI - CONTAINER START TESTS")
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
    parser = argparse.ArgumentParser(description='Test container start functionality')
    parser.add_argument('--test', help='Run a specific test: existing, new-existing, new-nonexisting, multi')
    parser.add_argument('--cleanup', action='store_true', help='Just clean up test containers')
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup_test_containers()
        sys.exit(0)
    
    if args.test:
        if args.test == 'existing':
            test_start_existing_container()
        elif args.test == 'new-existing':
            test_start_nonexistent_container_existing_image()
        elif args.test == 'new-nonexisting':
            test_start_nonexistent_container_nonexistent_image()
        elif args.test == 'multi':
            test_all_images()
        else:
            print(f"Unknown test: {args.test}")
    else:
        success = run_all_tests()
        sys.exit(0 if success else 1) 