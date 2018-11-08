#!/usr/bin/python3
# System integration tests of netplan-generate. NM and networkd are
# started on the generated configuration, using emulated ethernets (veth) and
# Wifi (mac80211-hwsim). These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2016 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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

import os
import sys
import re
import time
import subprocess
import tempfile
import unittest
import shutil

for program in ['wpa_supplicant', 'hostapd', 'dnsmasq']:
    if subprocess.call(['which', program], stdout=subprocess.PIPE) != 0:
        sys.stderr.write('%s is required for this test suite, but not available. Skipping\n' % program)
        sys.exit(0)

nm_uses_dnsmasq = b'dns=dnsmasq' in subprocess.check_output(['NetworkManager', '--print-config'])


def resolved_in_use():
    return os.path.isfile('/run/systemd/resolve/resolv.conf')


class NetworkTestBase(unittest.TestCase):
    '''Common functionality for network test cases

    setUp() creates two test wlan devices, one for a simulated access point
    (self.dev_w_ap), the other for a simulated client device
    (self.dev_w_client), and two test ethernet devices (self.dev_e_{ap,client}
    and self.dev_e2_{ap,client}.

    Each test should call self.setup_ap() or self.setup_eth() with the desired
    configuration.
    '''
    @classmethod
    def setUpClass(klass):
        # ensure we have this so that iw works
        subprocess.check_call(['modprobe', 'cfg80211'])

        # ensure NM can manage our fake eths
        os.makedirs('/run/udev/rules.d', exist_ok=True)
        with open('/run/udev/rules.d/99-nm-veth-test.rules', 'w') as f:
            f.write('ENV{ID_NET_DRIVER}=="veth", ENV{INTERFACE}=="eth42|eth43", ENV{NM_UNMANAGED}="0"\n')
        subprocess.check_call(['udevadm', 'control', '--reload'])

        # set regulatory domain "EU", so that we can use 80211.a 5 GHz channels
        out = subprocess.check_output(['iw', 'reg', 'get'], universal_newlines=True)
        m = re.match('^(?:global\n)?country (\S+):', out)
        assert m
        klass.orig_country = m.group(1)
        subprocess.check_call(['iw', 'reg', 'set', 'EU'])

    @classmethod
    def tearDownClass(klass):
        subprocess.check_call(['iw', 'reg', 'set', klass.orig_country])
        try:
            os.remove('/run/NetworkManager/conf.d/test-blacklist.conf')
        except FileNotFoundError:
            pass
        try:
            os.remove('/run/udev/rules.d/99-nm-veth-test.rules')
        except FileNotFoundError:
            pass

    def tearDown(self):
        subprocess.call(['systemctl', 'stop', 'NetworkManager', 'systemd-networkd', 'netplan-wpa@*',
                                              'systemd-networkd.socket'])
        # NM has KillMode=process and leaks dhclient processes
        subprocess.call(['systemctl', 'kill', 'NetworkManager'])
        subprocess.call(['systemctl', 'reset-failed', 'NetworkManager', 'systemd-networkd'],
                        stderr=subprocess.DEVNULL)
        shutil.rmtree('/etc/netplan', ignore_errors=True)
        shutil.rmtree('/run/NetworkManager', ignore_errors=True)
        shutil.rmtree('/run/systemd/network', ignore_errors=True)
        try:
            os.remove('/run/systemd/generator/netplan.stamp')
        except FileNotFoundError:
            pass

    @classmethod
    def create_devices(klass):
        '''Create Access Point and Client devices with mac80211_hwsim and veth'''

        if os.path.exists('/sys/module/mac80211_hwsim'):
            raise SystemError('mac80211_hwsim module already loaded')
        if os.path.exists('/sys/class/net/eth42'):
            raise SystemError('eth42 interface already exists')

        # create virtual ethernet devs
        subprocess.check_call(['ip', 'link', 'add', 'name', 'eth42', 'type',
                               'veth', 'peer', 'name', 'veth42'])
        klass.dev_e_ap = 'veth42'
        klass.dev_e_client = 'eth42'
        out = subprocess.check_output(['ip', '-br', 'link', 'show', 'dev', 'eth42'],
                                      universal_newlines=True)
        klass.dev_e_client_mac = out.split()[2]
        subprocess.check_call(['ip', 'link', 'add', 'name', 'eth43', 'type',
                               'veth', 'peer', 'name', 'veth43'])
        klass.dev_e2_ap = 'veth43'
        klass.dev_e2_client = 'eth43'
        out = subprocess.check_output(['ip', '-br', 'link', 'show', 'dev', 'eth43'],
                                      universal_newlines=True)
        klass.dev_e2_client_mac = out.split()[2]

        # create virtual wlan devs
        before_wlan = set([c for c in os.listdir('/sys/class/net') if c.startswith('wlan')])
        subprocess.check_call(['modprobe', 'mac80211_hwsim'])
        # wait 5 seconds for fake devices to appear
        timeout = 50
        while timeout > 0:
            after_wlan = set([c for c in os.listdir('/sys/class/net') if c.startswith('wlan')])
            if len(after_wlan) - len(before_wlan) >= 2:
                break
            timeout -= 1
            time.sleep(0.1)
        else:
            raise SystemError('timed out waiting for fake devices to appear')

        devs = list(after_wlan - before_wlan)
        klass.dev_w_ap = devs[0]
        klass.dev_w_client = devs[1]

        # don't let NM trample over our fake AP
        os.makedirs('/run/NetworkManager/conf.d', exist_ok=True)
        with open('/run/NetworkManager/conf.d/test-blacklist.conf', 'w') as f:
            f.write('[main]\nplugins=keyfile\n[keyfile]\nunmanaged-devices+=nptestsrv,%s\n' % klass.dev_w_ap)
        # work around https://launchpad.net/bugs/1615044
        with open('/run/NetworkManager/conf.d/11-globally-managed-devices.conf', 'w') as f:
            f.write('[keyfile]\nunmanaged-devices=')

    @classmethod
    def shutdown_devices(klass):
        '''Remove test wlan devices'''

        subprocess.check_call(['rmmod', 'mac80211_hwsim'])
        subprocess.check_call(['ip', 'link', 'del', 'dev', klass.dev_e_ap])
        subprocess.check_call(['ip', 'link', 'del', 'dev', klass.dev_e2_ap])
        subprocess.call(['ip', 'link', 'del', 'dev', 'mybr'],
                        stderr=subprocess.PIPE)
        klass.dev_w_ap = None
        klass.dev_w_client = None
        klass.dev_e_ap = None
        klass.dev_e_client = None
        klass.dev_e2_ap = None
        klass.dev_e2_client = None

    def setUp(self):
        '''Create test devices and workdir'''

        self.create_devices()
        self.addCleanup(self.shutdown_devices)
        self.workdir_obj = tempfile.TemporaryDirectory()
        self.workdir = self.workdir_obj.name
        self.config = '/etc/netplan/01-main.yaml'
        os.makedirs('/etc/netplan', exist_ok=True)

        # create static entropy file to avoid draining/blocking on /dev/random
        self.entropy_file = os.path.join(self.workdir, 'entropy')
        with open(self.entropy_file, 'wb') as f:
            f.write(b'012345678901234567890')

    def setup_ap(self, hostapd_conf, ipv6_mode):
        '''Set up simulated access point

        On self.dev_w_ap, run hostapd with given configuration. Setup dnsmasq
        according to ipv6_mode, see start_dnsmasq().

        This is torn down automatically at the end of the test.
        '''
        # give our AP an IP
        subprocess.check_call(['ip', 'a', 'flush', 'dev', self.dev_w_ap])
        if ipv6_mode is not None:
            subprocess.check_call(['ip', 'a', 'add', '2600::1/64', 'dev', self.dev_w_ap])
        else:
            subprocess.check_call(['ip', 'a', 'add', '192.168.5.1/24', 'dev', self.dev_w_ap])

        self.start_hostapd(hostapd_conf)
        self.start_dnsmasq(ipv6_mode, self.dev_w_ap)

    def setup_eth(self, ipv6_mode, start_dnsmasq=True):
        '''Set up simulated ethernet router

        On self.dev_e_ap, run dnsmasq according to ipv6_mode, see
        start_dnsmasq().

        This is torn down automatically at the end of the test.
        '''
        # give our router an IP
        subprocess.check_call(['ip', 'a', 'flush', 'dev', self.dev_e_ap])
        if ipv6_mode is not None:
            subprocess.check_call(['ip', 'a', 'add', '2600::1/64', 'dev', self.dev_e_ap])
            subprocess.check_call(['ip', 'a', 'add', '2601::1/64', 'dev', self.dev_e2_ap])
        else:
            subprocess.check_call(['ip', 'a', 'add', '192.168.5.1/24', 'dev', self.dev_e_ap])
            subprocess.check_call(['ip', 'a', 'add', '192.168.6.1/24', 'dev', self.dev_e2_ap])
        subprocess.check_call(['ip', 'link', 'set', self.dev_e_ap, 'up'])
        subprocess.check_call(['ip', 'link', 'set', self.dev_e2_ap, 'up'])
        if start_dnsmasq:
            self.start_dnsmasq(ipv6_mode, self.dev_e_ap)

    #
    # Internal implementation details
    #

    @classmethod
    def poll_text(klass, logpath, string, timeout=50):
        '''Poll log file for a given string with a timeout.

        Timeout is given in deciseconds.
        '''
        log = ''
        while timeout > 0:
            if os.path.exists(logpath):
                break
            timeout -= 1
            time.sleep(0.1)
        assert timeout > 0, 'Timed out waiting for file %s to appear' % logpath

        with open(logpath) as f:
            while timeout > 0:
                line = f.readline()
                if line:
                    log += line
                    if string in line:
                        break
                    continue
                timeout -= 1
                time.sleep(0.1)

        assert timeout > 0, 'Timed out waiting for "%s":\n------------\n%s\n-------\n' % (string, log)

    def start_hostapd(self, conf):
        hostapd_conf = os.path.join(self.workdir, 'hostapd.conf')
        with open(hostapd_conf, 'w') as f:
            f.write('interface=%s\ndriver=nl80211\n' % self.dev_w_ap)
            f.write(conf)

        log = os.path.join(self.workdir, 'hostapd.log')
        p = subprocess.Popen(['hostapd', '-e', self.entropy_file, '-f', log, hostapd_conf],
                             stdout=subprocess.PIPE)
        self.addCleanup(p.wait)
        self.addCleanup(p.terminate)
        self.poll_text(log, '' + self.dev_w_ap + ': AP-ENABLED')

    def start_dnsmasq(self, ipv6_mode, iface):
        '''Start dnsmasq.

        If ipv6_mode is None, IPv4 is set up with DHCP. If it is not None, it
        must be a valid dnsmasq mode, i. e. a combination of "ra-only",
        "slaac", "ra-stateless", and "ra-names". See dnsmasq(8).
        '''
        if ipv6_mode is None:
            if iface == self.dev_e2_ap:
                dhcp_range = '192.168.6.10,192.168.6.200'
            else:
                dhcp_range = '192.168.5.10,192.168.5.200'
        else:
            if iface == self.dev_e2_ap:
                dhcp_range = '2601::10,2601::20'
            else:
                dhcp_range = '2600::10,2600::20'
            if ipv6_mode:
                dhcp_range += ',' + ipv6_mode

        self.dnsmasq_log = os.path.join(self.workdir, 'dnsmasq-%s.log' % iface)
        lease_file = os.path.join(self.workdir, 'dnsmasq-%s.leases' % iface)

        p = subprocess.Popen(['dnsmasq', '--keep-in-foreground', '--log-queries',
                              '--log-facility=' + self.dnsmasq_log,
                              '--conf-file=/dev/null',
                              '--dhcp-leasefile=' + lease_file,
                              '--bind-interfaces',
                              '--interface=' + iface,
                              '--except-interface=lo',
                              '--enable-ra',
                              '--dhcp-range=' + dhcp_range])
        self.addCleanup(p.wait)
        self.addCleanup(p.terminate)

        if ipv6_mode is not None:
            self.poll_text(self.dnsmasq_log, 'IPv6 router advertisement enabled')
        else:
            self.poll_text(self.dnsmasq_log, 'DHCP, IP range')

    def assert_iface_up(self, iface, expected_ip_a=None, unexpected_ip_a=None):
        '''Assert that client interface is up'''

        out = subprocess.check_output(['ip', 'a', 'show', 'dev', iface],
                                      universal_newlines=True)
        if 'bond' not in iface:
            self.assertIn('state UP', out)
        if expected_ip_a:
            for r in expected_ip_a:
                self.assertRegex(out, r, out)
        if unexpected_ip_a:
            for r in unexpected_ip_a:
                self.assertNotRegex(out, r, out)

        if iface == self.dev_w_client:
            out = subprocess.check_output(['iw', 'dev', iface, 'link'],
                                          universal_newlines=True)
            # self.assertIn('Connected to ' + self.mac_w_ap, out)
            self.assertIn('SSID: fake net', out)

    def generate_and_settle(self):
        '''Generate config, launch and settle NM and networkd'''

        # regenerate netplan config
        subprocess.check_call(['netplan', 'apply'])
        # start NM so that we can verify that it does not manage anything
        subprocess.check_call(['systemctl', 'start', '--no-block', 'NetworkManager.service'])
        # wait until networkd is done
        if self.is_active('systemd-networkd.service'):
            if subprocess.call(['/lib/systemd/systemd-networkd-wait-online', '--quiet', '--timeout=50']) != 0:
                subprocess.call(['journalctl', '-b', '--no-pager', '-t', 'systemd-networkd'])
                st = subprocess.check_output(['networkctl'], stderr=subprocess.PIPE, universal_newlines=True)
                st_e = subprocess.check_output(['networkctl', 'status', self.dev_e_client],
                                               stderr=subprocess.PIPE, universal_newlines=True)
                st_e2 = subprocess.check_output(['networkctl', 'status', self.dev_e2_client],
                                                stderr=subprocess.PIPE, universal_newlines=True)
                self.fail('timed out waiting for networkd to settle down:\n%s\n%s\n%s' % (st, st_e, st_e2))

        if subprocess.call(['nm-online', '--quiet', '--timeout=120', '--wait-for-startup']) != 0:
            self.fail('timed out waiting for NetworkManager to settle down')

    def nm_wait_connected(self, iface, timeout):
        for t in range(timeout):
            try:
                out = subprocess.check_output(['nmcli', 'dev', 'show', iface])
            except subprocess.CalledProcessError:
                out = b''
            if b'(connected' in out:
                break
            time.sleep(1)
        else:
            self.fail('timed out waiting for %s to get connected by NM:\n%s' % (iface, out.decode()))

    @classmethod
    def is_active(klass, unit):
        '''Check if given unit is active or activating'''

        p = subprocess.Popen(['systemctl', 'is-active', unit], stdout=subprocess.PIPE)
        out = p.communicate()[0]
        return p.returncode == 0 or out.startswith(b'activating')


class _CommonTests:

    def test_empty_yaml_lp1795343(self):
        with open(self.config, 'w') as f:
            f.write('''''')
        self.generate_and_settle()

    @unittest.skip("Unsupported matching by driver / wifi matching makes this untestable for now")
    def test_mapping_for_driver(self):
        self.setup_ap('hw_mode=b\nchannel=1\nssid=fake net', None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    wifi_ifs:
      match:
        driver: mac80211_hwsim
      dhcp4: yes
      access-points:
        "fake net": {}
        decoy: {}''' % {'r': self.backend})
        self.generate_and_settle()
        p = subprocess.Popen(['netplan', 'generate', '--mapping', 'mac80211_hwsim'],
                             stdout=subprocess.PIPE)
        out = p.communicate()[0]
        self.assertEquals(p.returncode, 1)
        self.assertIn(b'mac80211_hwsim', out)

    def test_eth_and_bridge(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])

        # ensure that they do not get managed by NM for foreign backends
        expected_state = (self.backend == 'NetworkManager') and 'connected' or 'unmanaged'
        out = subprocess.check_output(['nmcli', 'dev'], universal_newlines=True)
        for i in [self.dev_e_client, self.dev_e2_client, 'mybr']:
            self.assertRegex(out, '%s\s+(ethernet|bridge)\s+%s' % (i, expected_state))

    def test_eth_mtu(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    enmtus:
      match: {name: %(e2c)s}
      mtu: 1492
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 192.168.6.[0-9]+/24'])
        out = subprocess.check_output(['ip', 'a', 'show', self.dev_e2_client],
                                      universal_newlines=True)
        self.assertTrue('mtu 1492' in out, "checking MTU, should be 1492")

    def test_eth_mac(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    enmac:
      match: {name: %(e2c)s}
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 192.168.6.[0-9]+/24', '00:01:02:03:04:05'],
                             ['master'])
        out = subprocess.check_output(['ip', 'link', 'show', self.dev_e2_client],
                                      universal_newlines=True)
        self.assertTrue('ether 00:01:02:03:04:05' in out)
        subprocess.check_call(['ip', 'link', 'set', self.dev_e2_client,
                               'address', self.dev_e2_client_mac])

    def test_bridge_path_cost(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        path-cost:
          ethbr: 50
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/path_cost' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '50')

    def test_bridge_ageing_time(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        ageing-time: 21
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/ageing_time') as f:
            self.assertEqual(f.read().strip(), '2100')

    def test_bridge_max_age(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        max-age: 12
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/max_age') as f:
            self.assertEqual(f.read().strip(), '1200')

    def test_bridge_hello_time(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        hello-time: 1
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/hello_time') as f:
            self.assertEqual(f.read().strip(), '100')

    def test_bridge_forward_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        forward-delay: 10
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/forward_delay') as f:
            self.assertEqual(f.read().strip(), '1000')

    def test_bridge_stp_false(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        hello-time: 100000
        max-age: 100000
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/stp_state') as f:
            self.assertEqual(f.read().strip(), '0')

    def test_bond_base(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)

    def test_bond_primary_slave(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [%(ec)s, %(e2c)s]
      parameters:
        mode: active-backup
        primary: %(ec)s
      addresses: [ '10.10.10.1/24' ]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 10.10.10.1/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e_client, result)
            self.assertIn(self.dev_e2_client, result)
        with open('/sys/class/net/mybond/bonding/primary') as f:
            self.assertEqual(f.read().strip(), '%(ec)s' % {'ec': self.dev_e_client})

    def test_bond_all_slaves_active(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        all-slaves-active: true
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/all_slaves_active') as f:
            self.assertEqual(f.read().strip(), '1')

    def test_bond_mode_8023ad(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), '802.3ad 4')

    def test_bond_mode_8023ad_adselect(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
        ad-select: bandwidth
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/ad_select') as f:
            self.assertEqual(f.read().strip(), 'bandwidth 1')

    def test_bond_mode_8023ad_lacp_rate(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
        lacp-rate: fast
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/lacp_rate') as f:
            self.assertEqual(f.read().strip(), 'fast 1')

    def test_bond_mode_activebackup_failover_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: active-backup
        fail-over-mac-policy: follow
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'active-backup 1')
        with open('/sys/class/net/mybond/bonding/fail_over_mac') as f:
            self.assertEqual(f.read().strip(), 'follow 2')

    def test_bond_mode_balance_xor(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-xor
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-xor 2')

    def test_bond_mode_balance_rr(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-rr
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-rr 0')

    def test_bond_mode_balance_rr_pps(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-rr
        packets-per-slave: 15
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-rr 0')
        with open('/sys/class/net/mybond/bonding/packets_per_slave') as f:
            self.assertEqual(f.read().strip(), '15')

    def test_bond_resend_igmp(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  bonds:
    mybond:
      interfaces: [ethbn, ethb2]
      parameters:
        mode: balance-rr
        mii-monitor-interval: 50s
        resend-igmp: 100
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e_client, result)
            self.assertIn(self.dev_e2_client, result)
        with open('/sys/class/net/mybond/bonding/resend_igmp') as f:
            self.assertEqual(f.read().strip(), '100')

    @unittest.skip("fails due to networkd bug setting routes with dhcp")
    def test_routes_v4_with_dhcp(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
      routes:
          - to: 10.10.10.0/24
            via: 192.168.5.254
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 via 192.168.5.254',  # from static route
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_routes_v4(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses:
          - 192.168.5.99/24
      gateway4: 192.168.5.1
      routes:
          - to: 10.10.10.0/24
            via: 192.168.5.254
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 via 192.168.5.254',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_routes_v6(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["9876:BBBB::11/70"]
      gateway6: "9876:BBBB::1"
      routes:
          - to: 2001:f00f:f00f::1/64
            via: 9876:BBBB::5
            metric: 799''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet6 9876:bbbb::11/70'])
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'2001:f00f:f00f::/64 via 9876:bbbb::5',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 799',
                      subprocess.check_output(['ip', '-6', 'route', 'show', '2001:f00f:f00f::/64']))

    def test_manual_addresses(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["172.16.42.99/18", "1234:FFFF::42/64"]
      dhcp4: yes
    %(e2c)s:
      addresses: ["172.16.1.2/24"]
      gateway4: "172.16.1.1"
      nameservers:
        addresses: [172.1.2.3]
        search: ["fakesuffix"]
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 172.16.42.99/18',
                              'inet6 1234:ffff::42/64',
                              'inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 172.16.1.2/24'])

        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'default via 172.16.1.1',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e2_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e2_client]))

        # ensure that they do not get managed by NM for foreign backends
        expected_state = (self.backend == 'NetworkManager') and 'connected' or 'unmanaged'
        out = subprocess.check_output(['nmcli', 'dev'], universal_newlines=True)
        for i in [self.dev_e_client, self.dev_e2_client]:
            self.assertRegex(out, '%s\s+(ethernet|bridge)\s+%s' % (i, expected_state))

        with open('/etc/resolv.conf') as f:
                resolv_conf = f.read()

        if self.backend == 'NetworkManager' and nm_uses_dnsmasq:
            sys.stdout.write('[NM with dnsmasq] ')
            sys.stdout.flush()
            self.assertRegex(resolv_conf, 'search.*fakesuffix')
            # not easy to peek dnsmasq's brain, so check its logging
            out = subprocess.check_output(['journalctl', '--quiet', '-tdnsmasq', '-ocat', '--since=-30s'],
                                          universal_newlines=True)
            self.assertIn('nameserver 172.1.2.3', out)
        elif resolved_in_use():
            sys.stdout.write('[resolved] ')
            sys.stdout.flush()
            out = subprocess.check_output(['systemd-resolve', '--status'], universal_newlines=True)
            self.assertIn('DNS Servers: 172.1.2.3', out)
            self.assertIn('fakesuffix', out)
        else:
            sys.stdout.write('[/etc/resolv.conf] ')
            sys.stdout.flush()
            self.assertRegex(resolv_conf, 'search.*fakesuffix')
            # /etc/resolve.conf often already has three nameserver entries
            if 'nameserver 172.1.2.3' not in resolv_conf:
                self.assertGreaterEqual(resolv_conf.count('nameserver'), 3)

        # change the addresses, make sure that "apply" does not leave leftovers
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["172.16.5.3/20", "9876:BBBB::11/70"]
      gateway6: "9876:BBBB::1"
    %(e2c)s:
      addresses: ["172.16.7.2/30", "4321:AAAA::99/80"]
      dhcp4: yes
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 172.16.5.3/20'],
                             ['inet 192.168.5',   # old DHCP
                              'inet 172.16.42',   # old static IPv4
                              'inet6 1234'])      # old static IPv6
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 172.16.7.2/30',
                              'inet6 4321:aaaa::99/80',
                              'inet 192.168.6.[0-9]+/24'],  # from DHCP
                             ['inet 172.16.1'])   # old static IPv4

        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'default via 192.168.6.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e2_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e2_client]))

    def test_dhcp6(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: yes
      accept-ra: yes
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, ['inet6 2600:'], ['inet 192.168'])

    def test_vlan(self):
        # we create two VLANs on e2c, and run dnsmasq on ID 2002 to test DHCP via VLAN
        self.setup_eth(None, start_dnsmasq=False)
        self.start_dnsmasq(None, self.dev_e2_ap)
        subprocess.check_call(['ip', 'link', 'add', 'link', self.dev_e2_ap,
                               'name', 'nptestsrv', 'type', 'vlan', 'id', '2002'])
        subprocess.check_call(['ip', 'a', 'add', '192.168.5.1/24', 'dev', 'nptestsrv'])
        subprocess.check_call(['ip', 'link', 'set', 'nptestsrv', 'up'])
        self.start_dnsmasq(None, 'nptestsrv')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s: {}
    myether:
      match: {name: %(e2c)s}
      dhcp4: yes
  vlans:
    nptestone:
      id: 1001
      link: myether
      addresses: [10.9.8.7/24]
    nptesttwo:
      id: 2002
      link: myether
      dhcp4: true
      ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()

        self.assert_iface_up('nptestone', ['nptestone@' + self.dev_e2_client, 'inet 10.9.8.7/24'])
        self.assert_iface_up('nptesttwo', ['nptesttwo@' + self.dev_e2_client, 'inet 192.168.5'])
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', 'nptestone']))
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', 'nptesttwo']))

    def test_vlan_mac_address(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'myvlan'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  vlans:
    myvlan:
      id: 101
      link: ethbn
      macaddress: aa:bb:cc:dd:ee:22
        ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up('myvlan', ['myvlan@' + self.dev_e_client])
        with open('/sys/class/net/myvlan/address') as f:
            self.assertEqual(f.read().strip(), 'aa:bb:cc:dd:ee:22')

    def test_wifi_ipv4_open(self):
        self.setup_ap('hw_mode=b\nchannel=1\nssid=fake net', None)

        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net": {}
        decoy: {}''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle()
        # nm-online doesn't wait for wifis, argh
        if self.backend == 'NetworkManager':
            self.nm_wait_connected(self.dev_w_client, 60)

        self.assert_iface_up(self.dev_w_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')

    def test_wifi_ipv4_wpa2(self):
        self.setup_ap('''hw_mode=g
channel=1
ssid=fake net
wpa=1
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
wpa_passphrase=12345678
''', None)

        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net":
          password: 12345678
        decoy: {}''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle()
        # nm-online doesn't wait for wifis, argh
        if self.backend == 'NetworkManager':
            self.nm_wait_connected(self.dev_w_client, 60)

        self.assert_iface_up(self.dev_w_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')

    def test_mix_bridge_on_bond(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'bond0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  bridges:
    br0:
      interfaces: [bond0]
      addresses: ['192.168.0.2/24']
  bonds:
    bond0:
      interfaces: [ethb2]
      parameters:
        mode: balance-rr
        mii-monitor-interval: 5
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e2_client,
                             ['master bond0'],
                             ['inet '])
        self.assert_iface_up('bond0',
                             ['master br0'])
        ipaddr = subprocess.check_output(['ip', 'a', 'show', 'dev', 'br0'],
                                         universal_newlines=True)
        self.assertIn('inet 192.168', ipaddr)
        with open('/sys/class/net/bond0/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e2_client, result)

    def test_mix_vlan_on_bridge_on_bond(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'bond0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  vlans:
    vlan1:
      link: 'br0'
      id: 1
      addresses: [ '10.10.10.1/24' ]
  bridges:
    br0:
      interfaces: ['bond0', 'vlan2']
      parameters:
        stp: false
        path-cost:
          bond0: 1000
          vlan2: 2000
  bonds:
    bond0:
      interfaces: ['br1']
      parameters:
        mode: balance-rr
  bridges:
    br1:
      interfaces: ['ethb2']
  vlans:
    vlan2:
      link: ethbn
      id: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up('vlan1', ['vlan1@br0'])
        self.assert_iface_up('vlan2',
                             ['vlan2@' + self.dev_e_client, 'master br0'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master br1'],
                             ['inet '])
        self.assert_iface_up('bond0',
                             ['master br0'])


class TestNetworkd(NetworkTestBase, _CommonTests):
    backend = 'networkd'

    def test_link_route_v4(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses:
          - 192.168.5.99/24
      gateway4: 192.168.5.1
      routes:
          - to: 10.10.10.0/24
            scope: link
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 proto static scope link',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_eth_dhcp6_off(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      accept-ra: yes
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, ['inet6 2600:'], [])

    def test_eth_dhcp6_off_no_accept_ra(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      accept-ra: no
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, [], ['inet6 2600:'])

    def test_bond_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match:
        name: %(ec)s
        macaddress: %(ec_mac)s
  bonds:
    mybond:
      interfaces: [ethbn]
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend,
                       'ec': self.dev_e_client,
                       'e2c': self.dev_e2_client,
                       'ec_mac': self.dev_e_client_mac})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24', '00:01:02:03:04:05'])

    def test_bridge_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match:
        name: %(ec)s
        macaddress: %(ec_mac)s
  bridges:
    br0:
      interfaces: [ethbr]
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend,
                       'ec': self.dev_e_client,
                       'e2c': self.dev_e2_client,
                       'ec_mac': self.dev_e_client_mac})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master br0'], ['inet'])
        self.assert_iface_up('br0',
                             ['inet 192.168.5.[0-9]+/24', '00:01:02:03:04:05'])

    def test_bond_down_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        down-delay: 10s
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/downdelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_up_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        up-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/updelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_arp_interval(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [ 192.168.5.1 ]
        arp-interval: 50s
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_interval') as f:
            self.assertEqual(f.read().strip(), '50000')

    def test_bond_arp_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-interval: 50000
        arp-ip-targets: [ 192.168.5.1 ]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_ip_target') as f:
            self.assertEqual(f.read().strip(), '192.168.5.1')

    def test_bond_arp_all_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-all-targets: all
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_all_targets') as f:
            self.assertEqual(f.read().strip(), 'all 1')

    def test_bond_arp_validate(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_validate') as f:
            self.assertEqual(f.read().strip(), 'all 3')

    def test_bond_mac_rename(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn1:
      match: {name: %(ec)s}
      dhcp4: no
    ethbn2:
      match: {name: %(e2c)s}
      dhcp4: no
  bonds:
    mybond:
      interfaces: [ethbn1, ethbn2]
      macaddress: 00:0a:f7:72:a7:28
      mtu: 9000
      addresses: [ 192.168.5.9/24 ]
      gateway4: 192.168.5.1
      parameters:
        down-delay: 0
        lacp-rate: fast
        mii-monitor-interval: 100
        mode: 802.3ad
        transmit-hash-policy: layer3+4
        up-delay: 0
      ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],
                             ['inet '])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertIn(self.dev_e_client, f.read().strip())

    def test_bridge_anonymous(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             [],
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])

    def test_bridge_isolated(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: []
      addresses: [10.10.10.10/24]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        subprocess.check_call(['netplan', 'apply'])
        time.sleep(1)
        out = subprocess.check_output(['ip', 'a', 'show', 'dev', 'mybr'],
                                      universal_newlines=True)
        self.assertIn('inet 10.10.10.10/24', out)

    def test_bridge_port_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        port-priority:
          ethbr: 42
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/priority' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '42')

    @unittest.skip("networkd does not handle non-unicast routes correctly yet (Invalid argument)")
    def test_route_type_blackhole(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 10.10.10.0/24
          via: 10.20.10.100
          type: blackhole''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'blackhole 10.10.10.0/24',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_on_link(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      dhcp4: no
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 20.0.0.0/24
          via: 10.10.10.10
          on-link: true''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'20.0.0.0/24 via 10.10.10.10 proto static onlink',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_with_policy(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 40.0.0.0/24
          via: 10.20.10.55
          metric: 50
        - to: 40.0.0.0/24
          via: 10.20.10.88
          table: 99
          metric: 50
      routing-policy:
        - from: 10.20.10.0/24
          to: 40.0.0.0/24
          table: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'to 40.0.0.0/24 lookup 99',
                      subprocess.check_output(['ip', 'rule', 'show']))
        self.assertIn(b'40.0.0.0/24 via 10.20.10.88',
                      subprocess.check_output(['ip', 'route', 'show', 'table', '99']))


class TestNetworkManager(NetworkTestBase, _CommonTests):
    backend = 'NetworkManager'

    @unittest.skip("NetworkManager does not disable accept_ra: bug LP: #1704210")
    def test_eth_dhcp6_off(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, [], ['inet6 2600:'])

    @unittest.skip("NetworkManager does not support setting MAC for a bond")
    def test_bond_mac(self):
        pass

    @unittest.skip("NetworkManager does not support setting MAC for a bridge")
    def test_bridge_mac(self):
        pass

    def test_wifi_ap_open(self):
        # we use dev_w_client and dev_w_ap in switched roles here, to keep the
        # existing device blacklisting in NM; i. e. dev_w_client is the
        # NM-managed AP, and dev_w_ap the manually managed client
        with open(self.config, 'w') as f:
            f.write('''network:
  wifis:
    renderer: NetworkManager
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net":
          mode: ap''' % {'wc': self.dev_w_client})
        self.generate_and_settle()

        # nm-online doesn't wait for wifis, argh
        self.nm_wait_connected(self.dev_w_client, 60)

        out = subprocess.check_output(['iw', 'dev', self.dev_w_client, 'info'],
                                      universal_newlines=True)
        self.assertIn('type AP', out)
        self.assertIn('ssid fake net', out)

        # connect the other end
        subprocess.check_call(['ip', 'link', 'set', self.dev_w_ap, 'up'])
        subprocess.check_call(['iw', 'dev', self.dev_w_ap, 'connect', 'fake net'])
        out = subprocess.check_output(['dhclient', '-1', '-v', self.dev_w_ap],
                                      stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertIn('DHCPACK', out)
        out = subprocess.check_output(['iw', 'dev', self.dev_w_ap, 'info'],
                                      universal_newlines=True)
        self.assertIn('type managed', out)
        self.assertIn('ssid fake net', out)
        out = subprocess.check_output(['ip', 'a', 'show', self.dev_w_ap],
                                      universal_newlines=True)
        self.assertIn('state UP', out)
        self.assertIn('inet 10.', out)

    def test_bond_down_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        down-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/downdelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_up_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        up-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/updelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_arp_interval(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [ 192.168.5.1 ]
        arp-interval: 50000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_interval') as f:
            self.assertEqual(f.read().strip(), '50000')

    def test_bond_arp_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-interval: 50000
        arp-ip-targets: [ 192.168.5.1 ]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_ip_target') as f:
            self.assertEqual(f.read().strip(), '192.168.5.1')

    def test_bond_arp_all_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-all-targets: all
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_all_targets') as f:
            self.assertEqual(f.read().strip(), 'all 1')

    def test_bond_mode_balance_tlb_learn_interval(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-tlb
        mii-monitor-interval: 5
        learn-packet-interval: 15
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-tlb 5')
        with open('/sys/class/net/mybond/bonding/lp_interval') as f:
            self.assertEqual(f.read().strip(), '15')

    def test_bridge_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        priority: 16384
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/priority') as f:
            self.assertEqual(f.read().strip(), '16384')

    def test_bridge_port_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        port-priority:
          ethbr: 42
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/priority' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '42')


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
