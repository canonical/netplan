FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# netplan dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion \
    build-essential \
    cmake \
    gcovr \
    libcmocka-dev \
    libglib2.0-dev \
    libsystemd-dev \
    libyaml-dev \
    meson \
    network-manager \
    pandoc \
    pkg-config \
    pycodestyle \
    pyflakes3 \
    python3-cffi \
    python3-coverage \
    python3-dev \
    python3-pytest \
    python3-pytest-cov \
    python3-yaml \
    systemd \
    udev \
    uuid-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# devcontainer dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    sudo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN echo "ubuntu ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu

WORKDIR /workspace

USER ubuntu
