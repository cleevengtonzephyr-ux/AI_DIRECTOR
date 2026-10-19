"""
Shared egress sentinels for the Provider = CLOSED tests.

`no_egress()` replaces, for the duration of a `with` block, every standard
way to start a process or open a connection -- `subprocess.Popen` (hence
`subprocess.run`), the other `subprocess` helpers, `os.system`/`os.popen`,
`http.client` connections and socket connections -- by recorders that
refuse. It yields the list of attempts, which a test asserts stays empty.
Nothing real is ever started or contacted, whatever the code under test does.
"""

import contextlib
import http.client
import os
import socket
import subprocess
from unittest import mock


class EgressAttempt(AssertionError):
    """Raised by a sentinel: a process launch or a connection was attempted."""


_TARGETS = (
    (subprocess, "Popen"),
    (subprocess, "run"),
    (subprocess, "call"),
    (subprocess, "check_call"),
    (subprocess, "check_output"),
    (os, "system"),
    (os, "popen"),
    (http.client, "HTTPConnection"),
    (http.client, "HTTPSConnection"),
    (socket, "create_connection"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
)


@contextlib.contextmanager
def no_egress():
    attempts = []

    def refuse(label):
        def refused(*args, **kwargs):
            attempts.append(label)
            raise EgressAttempt(label)

        return refused

    with contextlib.ExitStack() as stack:
        for owner, name in _TARGETS:
            label = f"{getattr(owner, '__name__', type(owner).__name__)}.{name}"
            stack.enter_context(mock.patch.object(owner, name, refuse(label)))
        yield attempts


class NoEgressTestCase:
    """Mixin: every test of the case runs under `no_egress()` (`self.egress`)."""

    def setUp(self):
        super().setUp()
        context = no_egress()
        self.egress = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
