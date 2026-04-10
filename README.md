# Netplan - Declarative network configuration for various backends

[![Build+ABI](https://github.com/canonical/netplan/workflows/Build%20&%20ABI%20compatibility/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/build-abi.yml?query=branch%3Amain)
[![Test+Coverage](https://github.com/canonical/netplan/workflows/Unit%20tests%20&%20Coverage/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/check-coverage.yml?query=branch%3Amain)
[![CI](https://github.com/canonical/netplan/workflows/Autopkgtest%20CI/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/autopkgtest.yml?query=branch%3Amain)


# Website

http://netplan.io

# Documentation

An overview of the architecture can be found at [netplan.io/design](https://netplan.io/design)

Find the full [documentation for Netplan](https://netplan.readthedocs.io) on "Read the Docs".

To contribute documentation, these steps should get you started:
1. Fork and clone the repo:
    ```
    git clone git@github.com:your_user_name/netplan.git
    ```
2. Create a new branch:
    ```
    git checkout -b <your_branch_name>
    ```
3. Navigate to the `doc/` directory and make your contribution:
    ```
    cd doc
    ```
4. View your documentation in the browser by running the `make` command from within the `doc/` directory:
    ```
    make run
    ```

5. Test your contribution to ensure good quality.

6. Push your contribution to GitHub and create a pull request.

If you face issues, refer to our [comprehensive contribution guide](https://netplan.readthedocs.io/en/stable/contribute-docs/).

# Build using Meson

Steps to build Netplan using the [Meson](https://mesonbuild.com) build system inside the `build/` directory:

* meson setup build --prefix=/usr [-Db_coverage=true]
* meson compile -C build
* meson test -C build --verbose [TEST_NAME]
* meson install -C build --destdir ../tmproot

# Test a local build (backend: networkd)

After `meson install -C _build --destdir ../tmproot`, test the local build without touching the system install by passing environment variables that redirect the CLI to your build tree (`NETPLAN_GENERATE_PATH`, `NETPLAN_CONFIGURE_PATH`, `LD_LIBRARY_PATH`, `PYTHONPATH`). These are needed because the Python CLI resolves binary and library paths at runtime.

Prepare a test config (replace `eth0` with an interface present on your system):

```sh
cat > test.yaml << 'EOF'
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      dhcp4-overrides:
        route-metric: 200   # safe to verify: check with 'ip route show' after apply
EOF
chmod 600 test.yaml  # netplan enforces strict file permissions
```

`route-metric` is a good test knob: it changes the preference value on the DHCP-assigned default route (visible in `ip route show` as `metric 200`), but does not drop or alter the route itself, so connectivity is unaffected.

**Try** (safest — auto-reverts on timeout; press Enter to accept):

> Pass environment variables inline (`sudo VAR=VAL ...`) rather than `sudo -E`.
> Most systems enable `env_reset` in `/etc/sudoers`, which strips user variables even with `-E`.

```sh
sudo \
  NETPLAN_GENERATE_PATH="$(pwd)/_build/src/generate" \
  NETPLAN_CONFIGURE_PATH="$(pwd)/_build/src/configure" \
  LD_LIBRARY_PATH="$(pwd)/_build/src" \
  PYTHONPATH="$(pwd)/_build/python-cffi:$(pwd)" \
  tmproot/usr/sbin/netplan try --timeout 60 --config-file test.yaml
```

**Verify:**

```sh
sudo tmproot/usr/sbin/netplan get                        # merged config
networkctl status eth0                                   # runtime state
sudo cat /run/systemd/network/10-netplan-eth0.network    # backend files
```

# Bug reports

Please file bug reports in [Launchpad](https://bugs.launchpad.net/netplan/+filebug).

# Contact us

Please join us on [IRC in #netplan](https://web.libera.chat/gamja/?channels=%23netplan) at Libera.Chat.

Our mailing list is [here](https://lists.launchpad.net/netplan-developers/).

Email the list at [netplan-developers@lists.launchpad.net](mailto:netplan-developers@lists.launchpad.net).

