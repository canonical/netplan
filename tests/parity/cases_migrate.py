# Parity cases for `netplan migrate` (/etc/network/interfaces conversion).
#
# Most snippets come from TestIfupdownMigrate in tests/cli_legacy.py; the
# rest cover parser, ipaddress, int() and yaml.dump() corner cases of the
# Python implementation. Every snippet runs with --dry-run and writing.
#
# Copyright (C) 2026 Canonical, Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

ENV = {'ENABLE_TEST_COMMANDS': '1'}
IFACES = '{ROOT}/etc/network/interfaces'
NET = '{ROOT}/etc/network/'


def static4(opts, iface='en1'):
    return 'auto %s\niface %s inet static\n%s' % (iface, iface, opts)


def static6(opts, iface='en1'):
    return 'auto %s\niface %s inet6 static\n%s' % (iface, iface, opts)


def gateway(value):
    return static4('address 1.2.3.4/8\ngateway %s\n' % value)


# name -> interfaces content, or (content, {extra files})
SNIPPETS = {
    # tests/cli_legacy.py: configs which can be converted
    'legacy/only-empty-include': '# default interfaces file\nsource-directory /etc/network/interfaces.d',
    'legacy/loopback-only': 'auto lo\n#ignore me\niface lo inet loopback',
    'legacy/dhcp4': 'auto en1\niface en1 inet dhcp',
    'legacy/dhcp6': 'auto en1\niface en1 inet6 dhcp',
    'legacy/dhcp4-and-6': 'auto lo\niface lo inet loopback\n\nauto en1\niface en1 inet dhcp\niface en1 inet6 dhcp',
    'legacy/includedir-rel': ('iface lo inet loopback\nauto lo\nsource-directory interfaces.d', {
        NET + 'interfaces.d/std': 'auto en1\niface en1 inet dhcp',
        NET + 'interfaces.d/std.bak': 'some_bogus dontreadme'}),
    'legacy/includedir-abs': ('iface lo inet loopback\nauto lo\nsource-directory /etc/network/defs/my', {
        NET + 'defs/my/std': 'auto en1\niface en1 inet dhcp',
        NET + 'defs/my/std.bak': 'some_bogus dontreadme'}),
    'legacy/include-rel': ('iface lo inet loopback\nauto lo\nsource interfaces.d/*.cfg', {
        NET + 'interfaces.d/std.cfg': 'auto en1\niface en1 inet dhcp',
        NET + 'interfaces.d/std.cfgold': 'some_bogus dontreadme'}),
    'legacy/include-abs': ('iface lo inet loopback\nauto lo\nsource /etc/network/*.cfg', {
        NET + 'std.cfg': 'auto en1\niface en1 inet dhcp',
        NET + 'std.cfgold': 'some_bogus dontreadme'}),
    'legacy/allow': 'allow-hotplug en1\niface en1 inet dhcp\nallow-auto en2\niface en2 inet dhcp',
    'legacy/no-scripts': 'auto en1\niface en1 inet dhcp\nno-scripts en1',
    # static
    'legacy/static-ipv4-prefix': static4('address 1.2.3.4/8'),
    'legacy/static-ipv4-netmask': static4('address 1.2.3.4\nnetmask 255.0.0.0'),
    'legacy/static-ipv4-alias': static4('address 1.2.3.4/8\n') + static4('address 1.2.3.5/8', 'en1:1'),
    'legacy/static-ipv4-no-address': static4('netmask 1.2.3.4'),
    'legacy/static-ipv4-no-network': static4('address 1.2.3.4'),
    'legacy/static-ipv4-invalid-addr': static4('address 1.2.3.400/8'),
    'legacy/static-ipv4-invalid-netmask': static4('address 1.2.3.4\nnetmask 123.123.123.0'),
    'legacy/static-ipv4-invalid-prefixlen': static4('address 1.2.3.4/42'),
    'legacy/static-ipv4-unsupported-option': static4('address 1.2.3.4/24\nmetric 1280'),
    'legacy/static-ipv4-unknown-option': static4('address 1.2.3.4/24\nxyzzy 1280'),
    'legacy/static-ipv6-prefix': static6('address fc00:0123:4567:89ab:cdef::1234/64'),
    'legacy/static-ipv6-netmask': static6('address fc00:0123:4567:89ab:cdef::1234\nnetmask 64'),
    'legacy/static-ipv6-no-address': static6('netmask 64'),
    'legacy/static-ipv6-no-network': static6('address fc00:0123:4567:89ab:cdef::1234'),
    'legacy/static-ipv6-invalid-addr': static6('address fc00:0123:4567:89ab:cdef::12345/64'),
    'legacy/static-ipv6-invalid-netmask': static6('address fc00:0123:4567:89ab:cdef::1234\nnetmask 129'),
    'legacy/static-ipv6-invalid-prefixlen': static6('address fc00:0123:4567:89ab:cdef::1234/129'),
    'legacy/static-ipv6-unsupported-option': static6('address fc00:0123:4567:89ab:cdef::1234/64\nmetric 1280'),
    'legacy/static-ipv6-unknown-option': static6('address fc00:0123:4567:89ab:cdef::1234/64\nxyzzy 1280'),
    'legacy/static-ipv6-accept-ra-0': static6('address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 0'),
    'legacy/static-ipv6-accept-ra-1': static6('address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 1'),
    'legacy/static-ipv6-accept-ra-2': static6('address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 2'),
    'legacy/static-ipv6-accept-ra-unexpected': static6('address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra fish'),
    'legacy/static-gateway': '''auto en1
iface en1 inet static
  address 1.2.3.4
  netmask 255.0.0.0
  gateway 1.1.1.1
iface en1 inet6 static
  address fc00:0123:4567:89ab:cdef::1234/64
  gateway fc00:0123:4567:89ab::1''',
    'legacy/static-dns': '''auto en1
iface en1 inet static
  address 1.2.3.4
  netmask 255.0.0.0
  dns-nameservers 1.2.1.1  1.2.2.1
  dns-search weird.network
iface en1 inet6 static
  address fc00:0123:4567:89ab:cdef::1234/64
  dns-nameservers fc00:0123:4567:89ab:1::1  fc00:0123:4567:89ab:2::1''',
    'legacy/static-dns2': static4('address 1.2.3.4/8\ndns-search foo  foo.bar'),
    'legacy/static-mtu': static4('address 1.2.3.4/8\nmtu 1280'),
    'legacy/static-invalid-mtu': static4('address 1.2.3.4/8\nmtu fish'),
    'legacy/static-two-different-mtus': static4('address 1.2.3.4/8\nmtu 1280\n') +
    'iface en1 inet6 static\naddress 2001::1/64\nmtu 9000',
    'legacy/static-hwaddress': static4('address 1.2.3.4/8\nhwaddress 52:54:00:6b:3c:59'),
    'legacy/static-two-different-macs': static4('address 1.2.3.4/8\nhwaddress 52:54:00:6b:3c:59\n') +
    'iface en1 inet6 static\naddress 2001::1/64\nhwaddress 52:54:00:6b:3c:58',
    # configs which are not supported
    'legacy/noauto': 'iface en1 inet dhcp',
    'legacy/dhcp-options': 'auto en1\niface en1 inet dhcp\nup myhook',
    'legacy/mapping': 'mapping en*\n  script /some/path/mapscheme\nmap HOME en1-home\n\nauto map1\niface map1 inet dhcp',
    'legacy/unknown-allow': 'allow-foo en1\niface en1 inet dhcp',
    'legacy/unknown-stanza': 'foo en1\niface en1 inet dhcp',
    'legacy/unknown-family': 'auto en1\niface en1 inet7 dhcp',
    'legacy/unknown-method': 'auto en1\niface en1 inet mangle',
    'legacy/too-few-fields': 'auto en1\niface en1 inet',
    'legacy/too-many-fields': 'auto en1\niface en1 inet dhcp foo',

    # line reading and normalization
    'lines/crlf': 'auto en1\r\niface en1 inet dhcp\r\n',
    'lines/lone-cr': 'auto en1\riface en1 inet dhcp\r',
    'lines/indented-comment': '  # comment\n\t\nauto en1   \n  iface   en1\tinet  dhcp  \n',
    'lines/unicode-space': 'auto en1\x1c\niface en1 inet dhcp\x1f\n',
    'lines/bom': '﻿auto en1\niface en1 inet dhcp\n',
    'lines/continuation': 'auto en1\niface en1 inet static \\\n  address 1.2.3.4/24\n',
    'lines/invalid-utf8': b'auto en1\niface en1 inet dhcp\n# \xff\n',
    'lines/invalid-utf8-continuation': b'auto en1\n# \xe2\x28\xa1\niface en1 inet dhcp\n',
    'lines/truncated-utf8': b'auto en1\niface en1 inet dhcp\n#\xe2\x82',
    'lines/invalid-utf8-second-chunk': b'auto en1\niface en1 inet dhcp\n#' + b'x' * 9000 + b'\n\xc3\x28\n',
    'lines/invalid-utf8-include': ('auto en1\nsource /etc/network/bad\niface en1 inet dhcp\n', {
        NET + 'bad': b'# \x80\n'}),
    'lines/latin1-gateway': (b'auto en1\niface en1 inet static\naddress 1.2.3.4/8\ngateway caf\xe9\n'),

    # stanzas
    'stanza/auto-two-ifaces': 'auto en1 en2\niface en1 inet dhcp\n',
    'stanza/mapping-two-fields': 'mapping en1 en2\n',
    'stanza/no-scripts-no-arg': 'auto en1\niface en1 inet dhcp\nno-scripts\n',
    'stanza/iface-only': 'iface\n',
    'stanza/option-before-iface': 'auto en1\naddress 1.2.3.4\n',
    'stanza/option-without-value': 'auto en1\niface en1 inet dhcp\n  up\n',
    'stanza/option-after-auto': 'auto en1\niface en1 inet dhcp\nauto en2\nup foo\n',
    'stanza/duplicate-iface-family': static4('address 1.2.3.4/8\n') + 'iface en1 inet dhcp\n',
    'stanza/duplicate-iface-order': ('auto en1 \nauto en2\niface en2 inet dhcp\niface en1 inet6 dhcp\n'
                                     'iface en1 inet dhcp\niface en2 inet6 dhcp\n'),
    'stanza/duplicate-option': static4('address 1.2.3.4/8\naddress 1.2.3.5/16\n'),
    'stanza/loopback-not-auto': 'iface lo inet loopback\n',
    'stanza/loopback-options': 'auto lo\niface lo inet loopback\n  foo bar\n',
    'stanza/allow-hotplug-static': 'allow-hotplug en1\niface en1 inet static\n  address 10.0.0.1/24\n',
    'stanza/unknown-family-and-method': 'iface en1 inet7 mangle\n',
    'stanza/no-auto-second': 'auto en1\niface en1 inet dhcp\niface en2 inet dhcp\n',
    'stanza/many-ifaces': ''.join('auto en%d\niface en%d inet dhcp\n' % (i, i) for i in (10, 2, 1, 20)),

    # includes
    'include/source-multiple': ('auto lo\nsource /etc/network/interfaces.d/*\n', {
        NET + 'interfaces.d/a': 'auto en1\niface en1 inet dhcp\n',
        NET + 'interfaces.d/b': 'auto en2\niface en2 inet6 dhcp\n',
        NET + 'interfaces.d/.hidden': 'garbage\n'}),
    'include/source-question-mark': ('source /etc/network/if?.cfg\n', {
        NET + 'if1.cfg': 'auto en1\niface en1 inet dhcp\n'}),
    'include/source-char-class': ('source /etc/network/if[0-9].cfg\n', {
        NET + 'if1.cfg': 'auto en1\niface en1 inet dhcp\n'}),
    'include/source-no-match': 'source /etc/network/nothing/*\nauto en1\niface en1 inet dhcp\n',
    'include/source-plain-file': ('source extra\n', {NET + 'extra': 'auto en1\niface en1 inet dhcp\n'}),
    'include/source-missing-plain-file': 'source extra\nauto en1\niface en1 inet dhcp\n',
    'include/source-directory-match': ('source /etc/network/interfaces.d/*\n', {
        NET + 'interfaces.d/sub/x': 'auto en1\n'}),
    'include/source-twice': ('source a\nsource b\n', {
        NET + 'a': 'auto en1\niface en1 inet dhcp\n', NET + 'b': 'auto en2\niface en2 inet dhcp\n'}),
    'include/source-twice-first-no-match': ('source nothing*\nsource b\n', {
        NET + 'b': 'auto en2\niface en2 inet dhcp\n'}),
    'include/source-directory-then-source': ('source-directory interfaces.d\nsource b\n', {
        NET + 'interfaces.d/a': 'auto en1\niface en1 inet dhcp\n', NET + 'b': 'auto en2\n'}),
    'include/source-directory-empty-then-source': ('source-directory interfaces.d\nsource b\n', {
        NET + 'interfaces.d': {'dir': True}, NET + 'b': 'auto en2\niface en2 inet dhcp\n'}),
    'include/source-directory-invalid-names': ('source-directory interfaces.d\n', {
        NET + 'interfaces.d/a.cfg': 'garbage\n', NET + 'interfaces.d/b~': 'garbage\n',
        NET + 'interfaces.d/ok_1-x': 'auto en1\niface en1 inet dhcp\n'}),
    'include/source-directory-missing-midfile': 'auto en1\nsource-directory nothing\niface en1 inet dhcp\n',
    'include/source-directory-missing-after-iface': 'auto en1\niface en1 inet dhcp\nsource-directory nothing\nfoo\n',
    'include/source-directory-is-file': ('source-directory extra\n', {NET + 'extra': 'auto en1\n'}),
    'include/source-directory-subdir': ('source-directory interfaces.d\n', {
        NET + 'interfaces.d/sub/x': 'auto en1\n'}),
    'include/nested': ('source a\n', {
        NET + 'a': 'auto en1\nsource sub/b\n', NET + 'sub/b': 'iface en1 inet dhcp\nsource c\n',
        NET + 'sub/c': '  dns-search example.com\n'}),
    'include/tab-separated': 'source\t/etc/network/a\n',
    'include/options-across-files': ('auto en1\niface en1 inet static\nsource a\n', {
        NET + 'a': 'address 1.2.3.4/24\n'}),

    # dhcp
    'dhcp/multiple-options': 'auto en1\niface en1 inet dhcp\n  up a\n  down b\n  mtu 1500\n  hostname h\n',
    'dhcp/dns-and-hwaddress': ('auto en1\niface en1 inet dhcp\n  dns-nameservers 1.1.1.1\n'
                               '  dns-search a b\n  hwaddress 00:11:22:33:44:55\n'),
    'dhcp/hwaddress-ether': 'auto en1\niface en1 inet dhcp\n  hwaddress ether 00:11:22:33:44:55\n',
    'dhcp/two-macs': ('auto en1\niface en1 inet dhcp\n  hwaddress 00:11:22:33:44:55\n'
                      'iface en1 inet6 dhcp\n  hwaddress 00:11:22:33:44:56\n'),
    'dhcp/same-macs': ('auto en1\niface en1 inet dhcp\n  hwaddress 00:11:22:33:44:55\n'
                       'iface en1 inet6 dhcp\n  hwaddress 00:11:22:33:44:55\n'),
    'dhcp/alias': 'auto en1:1\niface en1:1 inet dhcp\n',
    'dhcp/dns-tab': 'auto en1\niface en1 inet dhcp\n  dns-nameservers 1.1.1.1\t8.8.8.8\n',

    # aliases
    'alias/static-then-dhcp6': 'auto en1:1\nauto en1\niface en1:1 inet static\n  address 1.2.3.4/8\niface en1:1 inet6 dhcp\n',
    'alias/static-then-dhcp6-base-not-auto': 'auto en1:1\niface en1:1 inet static\n  address 1.2.3.4/8\niface en1:1 inet6 dhcp\n',
    'alias/mtu-conflict': static4('address 1.2.3.4/8\nmtu 1500\n') + static4('address 1.2.3.5/8\nmtu 9000', 'en1:0'),
    'alias/mtu-same': static4('address 1.2.3.4/8\nmtu 1500\n') + static4('address 1.2.3.5/8\nmtu 01_500', 'en1:0'),
    'alias/gateway-overwrite': static4('address 1.2.3.4/8\ngateway 1.0.0.1\n') +
    static4('address 1.2.3.5/8\ngateway 1.0.0.2', 'en1:0'),
    'alias/multi-colon': static4('address 1.2.3.4/8', 'en1:a:b'),
    'alias/dns-merge': static4('address 1.2.3.4/8\ndns-nameservers 1.1.1.1\n') +
    static4('address 1.2.3.5/8\ndns-nameservers 8.8.8.8\ndns-search x', 'en1:1'),

    # static option validation
    'static/unsupported-and-unknown': static4('address 1.2.3.4/8\nxyzzy 1\nbroadcast 1.255.255.255'),
    'static/mtu-before-unknown': static4('address 1.2.3.4/8\nxyzzy 1\nmtu fish'),
    'static/accept-ra-inet': static4('address 1.2.3.4/8\naccept_ra 1'),
    'static/inet6-unsupported-dad': static6('address 2001::1/64\ndad-attempts 1'),
    'static/no-address-unknown-option': static4('foo bar'),
    'static/netmask-and-prefix': static4('address 1.2.3.4/8\nnetmask 255.255.0.0'),

    # MTU, as parsed by int()
    'mtu/plus': static4('address 1.2.3.4/8\nmtu +1500'),
    'mtu/negative': static4('address 1.2.3.4/8\nmtu -5'),
    'mtu/minus-zero': static4('address 1.2.3.4/8\nmtu -0'),
    'mtu/underscore': static4('address 1.2.3.4/8\nmtu 9_000'),
    'mtu/double-underscore': static4('address 1.2.3.4/8\nmtu 9__000'),
    'mtu/leading-zeros': static4('address 1.2.3.4/8\nmtu 0009000'),
    'mtu/arabic-digits': static4('address 1.2.3.4/8\nmtu ١٥٠٠'),
    'mtu/float': static4('address 1.2.3.4/8\nmtu 1e3'),
    'mtu/huge': static4('address 1.2.3.4/8\nmtu ' + '9' * 100),
    'mtu/too-many-digits': static4('address 1.2.3.4/8\nmtu ' + '9' * 4301),
    'mtu/with-space': static4('address 1.2.3.4/8\nmtu 1500 bytes'),

    # IPv4 addresses and netmasks
    'ipv4/hostmask': static4('address 10.1.2.3\nnetmask 0.0.0.255'),
    'ipv4/netmask-prefix': static4('address 10.1.2.3\nnetmask 24'),
    'ipv4/netmask-all-ones': static4('address 10.1.2.3\nnetmask 255.255.255.255'),
    'ipv4/netmask-zero': static4('address 10.1.2.3\nnetmask 0.0.0.0'),
    'ipv4/netmask-noncontiguous': static4('address 10.1.2.3\nnetmask 255.0.255.0'),
    'ipv4/netmask-garbage': static4('address 10.1.2.3\nnetmask fish'),
    'ipv4/netmask-slash': static4('address 10.1.2.3\nnetmask 24/8'),
    'ipv4/prefix-leading-zero': static4('address 10.1.2.3/024'),
    'ipv4/prefix-plus': static4('address 10.1.2.3/+24'),
    'ipv4/prefix-empty': static4('address 10.1.2.3/'),
    'ipv4/prefix-dotted': static4('address 10.1.2.3/255.255.0.0'),
    'ipv4/two-slashes': static4('address 10.1.2.3/24/8'),
    'ipv4/bad-addr-two-slashes': static4('address 10.1.2/24/8'),
    'ipv4/leading-zero': static4('address 10.01.2.3/24'),
    'ipv4/empty-octet': static4('address 10..2.3/24'),
    'ipv4/three-octets': static4('address 10.2.3/24'),
    'ipv4/long-octet': static4('address 10.0002.3.4/24'),
    'ipv4/non-digit': static4('address 10.a.3.4/24'),
    'ipv4/non-ascii-digit': static4('address 10.١.3.4/24'),
    'ipv4/empty': static4('address /24'),
    'ipv4/ipv6-address': static4('address 2001::1/64'),
    'ipv4/host-bits': static4('address 10.1.2.3/8'),

    # IPv6 addresses and prefixes
    'ipv6/mapped': static6('address ::ffff:1.2.3.4/96'),
    'ipv6/mapped-hex': static6('address ::ffff:102:304/96'),
    'ipv6/compat': static6('address ::1.2.3.4/96'),
    'ipv6/scope': static6('address fe80::1%eth0/64'),
    'ipv6/empty-scope': static6('address fe80::1%/64'),
    'ipv6/double-scope': static6('address fe80::1%a%b/64'),
    'ipv6/all-zero': static6('address ::/0'),
    'ipv6/trailing-zeros': static6('address 1:0:0:0:0:0:0:0/64'),
    'ipv6/two-zero-runs': static6('address 1:0:0:1:0:0:0:1/64'),
    'ipv6/single-zero': static6('address 1:0:1:1:1:1:1:1/64'),
    'ipv6/uppercase': static6('address FE80::ABCD/64'),
    'ipv6/too-long': static6('address 1111:2222:3333:4444:5555:6666:7777:8888:9999:aaaa/64'),
    'ipv6/way-too-long': static6('address ' + '1:' * 60 + '1/64'),
    'ipv6/two-double-colons': static6('address 1::2::3/64'),
    'ipv6/too-many-colons': static6('address 1:2:3:4:5:6:7:8:9/64'),
    'ipv6/too-few-parts': static6('address 1:2/64'),
    'ipv6/seven-parts': static6('address 1:2:3:4:5:6:7/64'),
    'ipv6/leading-colon': static6('address :1:2:3:4:5:6:7/64'),
    'ipv6/trailing-colon': static6('address 1:2:3:4:5:6:7:/64'),
    'ipv6/leading-colon-skip': static6('address :1::2/64'),
    'ipv6/trailing-colon-skip': static6('address 1::2:/64'),
    'ipv6/full-with-skip': static6('address 1:2:3:4::5:6:7:8/64'),
    'ipv6/bad-ipv4-suffix': static6('address ::1.2.3/64'),
    'ipv6/bad-ipv4-suffix-colons': static6('address 1:2:3:4:5:6:7:8:9:1.2.3.4/64'),
    'ipv6/hextet-too-long': static6('address 1::12345/64'),
    'ipv6/hextet-non-hex': static6('address 1::g/64'),
    'ipv6/empty': static6('address /64'),
    'ipv6/no-colon': static6('address 1.2.3.4/64'),
    'ipv6/netmask-dotted': static6('address 2001::1\nnetmask ffff:ffff::'),
    'ipv6/prefix-leading-zero': static6('address 2001::1/064'),
    'ipv6/prefix-128': static6('address 2001::1/128'),
    'ipv6/two-slashes': static6('address 2001::1/64/8'),
    'ipv6/gateway-and-accept-ra': static6('address 2001::1/64\ngateway 2001::ff\naccept_ra 0'),
    'ipv6/inet-and-inet6': static4('address 1.2.3.4/8\n') + 'iface en1 inet6 static\n  address 2001::1/64\n',

    # yaml.dump() styles
    'yaml/gateway-bool': gateway('yes'),
    'yaml/gateway-null': gateway('null'),
    'yaml/gateway-tilde': gateway('~'),
    'yaml/gateway-int': gateway('1234'),
    'yaml/gateway-octal': gateway('0777'),
    'yaml/gateway-hex': gateway('0x1F'),
    'yaml/gateway-binary': gateway('0b101'),
    'yaml/gateway-sexagesimal': gateway('1:20'),
    'yaml/gateway-sexagesimal-float': gateway('1:20.5'),
    'yaml/gateway-not-sexagesimal': gateway('1:60'),
    'yaml/gateway-float': gateway('1.5'),
    'yaml/gateway-float-exp': gateway('1.5e+3'),
    'yaml/gateway-inf': gateway('-.inf'),
    'yaml/gateway-nan': gateway('.NaN'),
    'yaml/gateway-dot-float': gateway('.5'),
    'yaml/gateway-date': gateway('2001-12-14'),
    'yaml/gateway-timestamp': gateway('2001-12-14t21:59:43.10-05:00'),
    'yaml/gateway-timestamp-space': gateway('2001-12-14 21:59:43.10 -5'),
    'yaml/gateway-merge': gateway('<<'),
    'yaml/gateway-equals': gateway('='),
    'yaml/gateway-star': gateway('*'),
    'yaml/gateway-anchor': gateway('&a'),
    'yaml/gateway-tag': gateway('!foo'),
    'yaml/gateway-percent': gateway('%foo'),
    'yaml/gateway-at': gateway('@foo'),
    'yaml/gateway-backtick': gateway('`foo'),
    'yaml/gateway-dash-space': gateway('- foo'),
    'yaml/gateway-dash': gateway('-foo'),
    'yaml/gateway-question': gateway('? foo'),
    'yaml/gateway-colon-space': gateway('a: b'),
    'yaml/gateway-colon-end': gateway('a:'),
    'yaml/gateway-leading-colon': gateway(':a'),
    'yaml/gateway-hash': gateway('a #b'),
    'yaml/gateway-hash-inside': gateway('a#b'),
    'yaml/gateway-leading-hash': gateway('#a'),
    'yaml/gateway-flow-chars': gateway('a,b[c]{d}'),
    'yaml/gateway-document-start': gateway('--- a'),
    'yaml/gateway-document-end': gateway('...'),
    'yaml/gateway-single-quote': gateway("it's"),
    'yaml/gateway-double-quote': gateway('say "hi"'),
    'yaml/gateway-backslash': gateway('a\\b'),
    'yaml/gateway-tab': gateway('a\tb'),
    'yaml/gateway-control': gateway('a\x01b\x07c\x1bd\x7f'),
    'yaml/gateway-unicode': gateway('café   \u0085﻿\U0001f600'),
    'yaml/gateway-long-plain': gateway(' '.join(['word%d' % i for i in range(40)])),
    'yaml/gateway-long-single': gateway(' '.join(['w:%d' % i for i in range(5)] + ['yes'] * 40) + ' :x'),
    'yaml/gateway-long-quoted-spaces': gateway('\'' + ' '.join(['word%d' % i for i in range(40)])),
    'yaml/gateway-long-double': gateway(' '.join(['wé%d' % i for i in range(40)])),
    'yaml/gateway-long-double-nospace': gateway('é' * 100),
    'yaml/gateway-long-double-double-spaces': gateway('é' + '  '.join(['x%d' % i for i in range(40)])),
    'yaml/gateway-long-nospace': gateway('x' * 200),
    'yaml/gateway-multiple-spaces': gateway('a   b ' * 30 + 'c'),
    'yaml/mac-sexagesimal': static4('address 1.2.3.4/8\nhwaddress 10:11:22:33:44:55'),
    'yaml/mac-plain': static4('address 1.2.3.4/8\nhwaddress 00:11:22:33:44:55'),
    'yaml/iface-int': 'auto 123\niface 123 inet dhcp\n',
    'yaml/iface-bool': 'auto on\niface on inet dhcp\n',
    'yaml/iface-null': 'auto null\niface null inet dhcp\n',
    'yaml/iface-unicode': 'auto ethé\niface ethé inet dhcp\n',
    'yaml/iface-quote': "auto 'eth\niface 'eth inet dhcp\n",
    'yaml/iface-long': 'auto %s\niface %s inet dhcp\n' % ('e' * 122, 'e' * 122),
    'yaml/iface-too-long': 'auto %s\niface %s inet dhcp\n' % ('e' * 123, 'e' * 123),
    'yaml/iface-too-long-quoted': 'auto %s\niface %s inet dhcp\n' % ('1' * 130, '1' * 130),
    'yaml/iface-too-long-unicode': 'auto %s\niface %s inet dhcp\n' % ('é' * 130, 'é' * 130),
    'yaml/iface-too-long-static': 'auto %s\niface %s inet static\n address 1.2.3.4/8\n' % ('e' * 130, 'e' * 130),
    'yaml/iface-sort': 'auto b\nauto B\nauto a\nauto é\nauto _\n' + ''.join(
        'iface %s inet dhcp\n' % i for i in ('b', 'B', 'a', 'é', '_')),
    'yaml/dns-values': ('auto en1\niface en1 inet dhcp\n  dns-nameservers yes 1:20 \'q\n'
                        '  dns-search on ~ a,b\n'),
}


def all_cases():
    out = []
    for name, spec in SNIPPETS.items():
        content, extra = spec if isinstance(spec, tuple) else (spec, {})
        files = {IFACES: content}
        files.update(extra)
        out.append(dict(id='migrate/%s/dry-run' % name, argv=['migrate', '--root-dir', '{ROOT}', '--dry-run'],
                        files=files, env=ENV))
        out.append(dict(id='migrate/%s/write' % name, argv=['migrate', '--root-dir', '{ROOT}'],
                        files=files, env=ENV))

    dhcp = 'auto en1\niface en1 inet dhcp\n'
    system = {'/etc/network/interfaces': dhcp}
    out += [
        # no --root-dir: the real /etc/network/interfaces
        dict(id='migrate/system/dry-run', argv=['migrate', '--dry-run'], files=system, env=ENV),
        dict(id='migrate/system/write', argv=['migrate'], files=system, env=ENV),
        dict(id='migrate/system/write-loopback', argv=['migrate'], env=ENV,
             files={'/etc/network/interfaces': 'auto lo\niface lo inet loopback\n'}),
        dict(id='migrate/system/source', argv=['migrate', '--dry-run'], env=ENV, files={
            '/etc/network/interfaces': 'source /etc/network/interfaces.d/*\nsource-directory interfaces.d\n',
            '/etc/network/interfaces.d/a': dhcp}),
        dict(id='migrate/system/empty-root-dir', argv=['migrate', '--root-dir', ''], files=system, env=ENV),
        dict(id='migrate/system/no-file-write', argv=['migrate'], env=ENV),
        # --root-dir spelling
        dict(id='migrate/root-dir/trailing-slash', argv=['migrate', '--root-dir', '{ROOT}/'], env=ENV, files={
            IFACES: 'source /etc/network/a\nsource-directory /etc/network/d\nsource-directory d\n',
            NET + 'a': dhcp, NET + 'd/b': 'auto en2\niface en2 inet6 dhcp\n'}),
        dict(id='migrate/root-dir/double-slash', argv=['migrate', '--root-dir', '{ROOT}//', '--dry-run'], env=ENV,
             files={IFACES: 'source a\n', NET + 'a': dhcp}),
        dict(id='migrate/root-dir/missing', argv=['migrate', '--root-dir', '{ROOT}/nonexistent'], env=ENV),
        # writing
        dict(id='migrate/write/no-interfaces-file', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV),
        dict(id='migrate/write/prev-run', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, '{ROOT}/etc/netplan/10-ifupdown.yaml': 'canary'}),
        dict(id='migrate/write/prev-run-dry-run', argv=['migrate', '--root-dir', '{ROOT}', '--dry-run'], env=ENV,
             files={IFACES: dhcp, '{ROOT}/etc/netplan/10-ifupdown.yaml': 'canary'}),
        dict(id='migrate/write/prev-run-symlink', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, '{ROOT}/etc/netplan/10-ifupdown.yaml': {'symlink': 'nowhere'}}),
        dict(id='migrate/write/netplan-dir-is-file', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, '{ROOT}/etc/netplan': 'not a directory'}),
        dict(id='migrate/write/etc-netplan-mode', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, '{ROOT}/etc/netplan': {'dir': True, 'mode': 0o700}}),
        dict(id='migrate/write/converted-exists', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, IFACES + '.netplan-converted': 'old'}),
        dict(id='migrate/write/converted-is-dir', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: dhcp, IFACES + '.netplan-converted/x': 'old'}),
        dict(id='migrate/write/interfaces-is-dir', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES + '/x': 'old'}),
        dict(id='migrate/write/interfaces-symlink', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: {'symlink': 'real'}, NET + 'real': dhcp}),
        dict(id='migrate/write/interfaces-dangling-symlink', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV,
             files={IFACES: {'symlink': 'nowhere'}}),
        dict(id='migrate/write/network-is-file', argv=['migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            '{ROOT}/etc/network': 'file'}),
        # --debug output is not compared, but must not change anything else
        dict(id='migrate/debug/static', argv=['--debug', 'migrate', '--root-dir', '{ROOT}'], env=ENV, files={
            IFACES: static4('address 1.2.3.4/8\ndns-search x\n'), NET + 'interfaces.d/a': dhcp}),
        dict(id='migrate/debug/include', argv=['migrate', '--debug', '--root-dir', '{ROOT}', '--dry-run'], env=ENV,
             files={IFACES: 'source-directory interfaces.d\nsource-directory missing\n',
                    NET + 'interfaces.d/a': dhcp}),
    ]
    return out
