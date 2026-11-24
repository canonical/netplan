import os

# Point call_cli() in test_utils to the Rust binary for all tests in this package.
# The binary is built by `cargo build --release` in netplan_cli_rs/.
# Override by setting NETPLAN_CLI_BINARY in the environment before running tests.
_rootdir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    'NETPLAN_CLI_BINARY',
    os.path.join(_rootdir, 'netplan_cli_rs', 'target', 'release', 'netplan'),
)
