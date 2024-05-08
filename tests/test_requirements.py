import asyncio
import json

import pytest
import os
from plumbum import BG, local, FG, TF
from edwh_nostr_messagebus.client import (
    OLClient,
    StopProcessingHandlers,
    listen_forever,
    send_and_disconnect,
)
import signal

from monstr.encrypt import Keys
from monstr.event.event import Event

PORT = '8888'
RELAY_URL = f"ws://127.0.0.1:{PORT}"


# noinspection PyStatementEffect
@pytest.fixture(scope='session')
def monstr_terminal():
    """

    monstr_terminal

    Fixture for setting up and running the monstr_terminal module.

    Returns:
        local: An reference to the installed python plumbum.local object for the monstr_terminal.

    Usage:
        The monstr_terminal fixture should be used as a pytest fixture with the 'session' scope.
        It can be used to set up and run the monstr_terminal module for testing purposes.

    """
    try:
        import monstr_terminal
    except:
        git, echo = local['git'], local['echo']

        echo['Cloning...'] & FG
        git['clone', '--recurse-submodules', 'https://github.com/monty888/monstr_terminal.git'] & FG
        echo['Building new venv'] & FG
        import venv
        venv.main(['monstr_terminal/venv'])
        echo['installing deps'] & FG
        pip = local['monstr_terminal/venv/bin/pip']
        pip['install', '-r', './monstr_terminal/requirements.txt'] & FG
        echo['installing monstr'] & FG
        pip['install', './monstr_terminal/monstr'] & FG
        echo['testing event_view'] & FG

    python = local['monstr_terminal/venv/bin/python']
    python['monstr_terminal/event_view.py'] & TF()
    yield python


@pytest.fixture(scope='session')
def relay(monstr_terminal):
    cmd = monstr_terminal['monstr_terminal/run_relay.py', '--port', PORT]
    future = cmd & BG
    yield future
    future.proc._proc.kill()


@pytest.fixture(scope='session')
def session_key():
    yield Keys()


def self_terminate():
    """send SIGHUP to our own pid, because it will hangup the asyncIO loop. """
    os.kill(os.getpid(), signal.SIGHUP)


def test_send_and_receive_some_messages(relay, session_key):
    messages = [dict(foo='bar')]
    success = False

    def wait_for_it(client: OLClient, js: str, event: Event) -> None:
        js = json.loads(js)
        if js['foo'] == 'bar':
            js['foo'] = 'baz'
            client.broadcast(js, tags=[["better", True]])
            self_terminate()
        elif js['foo'] == 'baz':
            nonlocal success
            success = True

    send_and_disconnect([RELAY_URL], session_key, messages)

    try:
        listen_forever(
            keys=session_key,
            relay=RELAY_URL,
            lookback=10,
            domain_handlers=[
                wait_for_it,
            ],
        )
    except asyncio.exceptions.CancelledError:
        pass

    assert success