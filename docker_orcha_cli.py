#!/usr/bin/env python3
"""
Docker Orchestration CLI

A modern, interactive CLI for managing Docker containers and orchestration tasks.
"""

import sys
import typer
from docker_orcha.cli.commands import app, interactive


if __name__ == '__main__':
    # If 'interactive' is the only argument, run interactive mode directly
    if len(sys.argv) == 2 and sys.argv[1] == 'interactive':
        interactive()
    else:
        app() 