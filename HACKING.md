# Hacking Guide

## Container Usage

### VS Code Dev Container

A devcontainer is provided under `.devcontainer/`.

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
2. Open this repository in VS Code.
3. Run `Dev Containers: Reopen in Container` from the Command Palette.

## Notes

- The Docker image is useful for reproducible builds and many tests.
- Some system-level integration scenarios (for example, full network service lifecycle behavior) are better exercised VM-based environments.
