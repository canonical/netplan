#!/usr/bin/python3
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

"""
Terminal / input handling
"""

import fcntl
import os
import termios
import select
import sys


class Terminal(object):
    """
    Do minimal terminal mangling to prompt users for input
    """

    def __init__(self, fd):
        self.fd = fd
        self.orig_flags = None
        self.orig_term = None
        self.save()

    def enable_echo(self):
        attrs = termios.tcgetattr(self.fd)
        attrs[3] = attrs[3] | termios.ICANON
        attrs[3] = attrs[3] | termios.ECHO
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def disable_echo(self):
        attrs = termios.tcgetattr(self.fd)
        attrs[3] = attrs[3] & ~termios.ICANON
        attrs[3] = attrs[3] & ~termios.ECHO
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def enable_nonblocking_io(self):
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def disable_nonblocking_io(self):
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)

    def get_confirmation_input(self, timeout=120, message=None):  # pragma: nocover (requires user input)
        """
        Get a "confirmation" input from the user, for at most (timeout)
        seconds. Optionally, customize the message to be displayed.

        timeout -- timeout to wait for input (default 120)
        message -- optional customized message ("Press ENTER to (message)")

        raises:
        InputAccepted -- the user confirmed the changes
        InputRejected -- the user rejected the changes
        """
        print("Do you want to keep these settings?\n\n")

        self.save()
        self.enable_nonblocking_io()

        if not message:
            message = "accept the new configuration"

        print("Press ENTER before the timeout to {}\n\n".format(message))
        timeout_now = timeout
        while (timeout_now > 0):
            print("Changes will revert in {:>{}} seconds".format(timeout_now, len(str(timeout))), end='\r')

            # wait at most 1 second for usable input from stdin
            select.select([sys.stdin], [], [], 1)
            try:
                # retrieve any input from the terminal. select() either has
                # timed out with no input, or found something we can retrieve.
                c = sys.stdin.read()
                if (c == '\n'):
                    self.reset()
                    # Yay, user has accepted the changes!
                    raise InputAccepted()
            except TypeError:
                # read() above is non-blocking, if there is nothing to read it
                # will return TypeError, which we should ignore -- on to the
                # next iteration until timeout.
                pass
            timeout_now -= 1

        # We reached the timeout for our loop, now revert our change for
        # non-blocking I/O and signal the caller the changes were essentially
        # rejected.
        self.reset()
        raise InputRejected()

    def save(self):
        """
        Save the terminal's current attributes and flags
        """
        self.orig_flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        self.orig_term = termios.tcgetattr(self.fd)

    def reset(self):
        """
        Reset the terminal to its original attributes and flags
        """
        termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.orig_term)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_flags)


class InputAccepted(Exception):
    """ Denotes has accepted input"""
    pass


class InputRejected(Exception):
    """ Denotes that the user has rejected input"""
    pass
