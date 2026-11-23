# Helpers for the netplan spread tasks; source from a task with
#   . "$SPREAD_PATH"/tests/spread/lib.sh

NETWORKD_BR54=/run/systemd/network/10-netplan-br54.network
TRY_STAMP=/run/netplan/netplan-try.ready

# Create a new io.netplan.Netplan.Config object and print its path
netplan_config_object() {
    busctl call --system io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Config \
        | sed 's/^o "\(.*\)"$/\1/'
}

# config_call OBJECT METHOD [SIGNATURE ARGS...]: call a Config method,
# printing busctl's reply (e.g. "b true"); fails if the call returns an error
config_call() {
    obj="$1"; shift
    method="$1"; shift
    busctl call --system io.netplan.Netplan "$obj" io.netplan.Netplan.Config "$method" "$@"
}

# The generated networkd configuration for br54 enables DHCPv4 or not
br54_backend_has_dhcp4() {
    grep -q '^DHCP=ipv4$' "$NETWORKD_BR54"
}

# Wait up to $1 seconds for no 'netplan try' process to be left
wait_for_try_to_finish() {
    for _ in $(seq "$1"); do
        if ! pgrep -f 'netplan try' >/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "'netplan try' still running after $1 seconds"
    return 1
}

# not CMD...: succeed if CMD fails (works under 'set -e', unlike '! CMD')
not() {
    if "$@"; then
        echo "unexpectedly succeeded: $*"
        return 1
    fi
}
