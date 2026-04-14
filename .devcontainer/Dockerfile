FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion \
    build-essential \
    cmake \
    gcovr \
    git \
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
    sudo \
    systemd \
    udev \
    uuid-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash netplan && \
    usermod -aG sudo netplan && \
    echo "netplan ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers.d/netplan

WORKDIR /workspace

USER netplan
