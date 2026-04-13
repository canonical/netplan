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

A Makefile wrapper is also provided for simplified usage. For that approach, please refer to the [Build using Makefile][makefile-section] section below.

Steps to build Netplan using the [Meson](https://mesonbuild.com) build system inside the `build/` directory:

* meson setup build --prefix=/usr [-Db_coverage=true]
* meson compile -C build
* meson test -C build --verbose [TEST_NAME]
* meson install -C build --destdir ../tmproot

# Build using Makefile

Convenience targets are available via `make`:

- `make` or `make default`  
  Set up the build directory (`_build`) and build the project

- `make check`  
  Build and run all tests in `_build`

- `make linting`  
  Run Meson `linting` and `codestyle` test targets

- `make check-coverage`  
  Set up a coverage build directory (`_build-cov`), build, and run coverage tests

- `make install [DESTDIR=../tmproot]`  
  Build and install into a staging root (defaults to `../tmproot`)

- `make clean`  
  Remove generated build and test artifacts

- `make run ARGS='<command>'`  
  Run the locally built CLI with the appropriate environment, e.g.:
  ```sh
  make run ARGS="help"
  ```

# Test local build

After running:

```sh
make
make install
```

you can test the locally built `netplan` without installing it system-wide:

```sh
make run ARGS="<command>"
```

This wrapper sets the required environment variables automatically:

`NETPLAN_GENERATE_PATH`
`NETPLAN_CONFIGURE_PATH`
`LD_LIBRARY_PATH`
`PYTHONPATH`

These are needed because the Python CLI resolves binary and library paths at runtime.

**Example**:

```sh
# build and install
make
make install

# run a command (netplan info)
make run ARGS="info"
```

*output*:

```sh
netplan.io:
  website: "https://netplan.io/"
  features:
  - dhcp-use-domains
  - auth-phase2
  - ipv6-mtu
  - modems
  - sriov
  - openvswitch
  - activation-mode
  - eswitch-mode
  - infiniband
  - regdom
  - vrf
  - vxlan
  - virtual-ethernet
  - dbus-config
  - generated-suppl
```

# Bug reports

Please file bug reports in [Launchpad](https://bugs.launchpad.net/netplan/+filebug).

# Contact us

Please join us on [IRC in #netplan](https://web.libera.chat/gamja/?channels=%23netplan) at Libera.Chat.

Our mailing list is [here](https://lists.launchpad.net/netplan-developers/).

Email the list at [netplan-developers@lists.launchpad.net](mailto:netplan-developers@lists.launchpad.net).

[makefile-section]: #build-using-makefile