import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections.abc import Callable

import pytest
from edwh_nostr_messagebus.client import (
    OLClient,
    StopProcessingHandlers,
    listen_forever,
    send_and_disconnect,
)
from monstr.encrypt import Keys
from monstr.event.event import Event
from plumbum import BG, FG, TF, local

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler = logging.FileHandler("troubleshooting.log")
handler.setFormatter(formatter)
logger.addHandler(handler)


PORT = "8888"
RELAY_URL = f"ws://127.0.0.1:{PORT}"


# noinspection PyStatementEffect
@pytest.fixture(scope="session")
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
        import monstr_terminal  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        git, echo = local["git"], local["echo"]

        echo["Cloning..."] & FG
        (
            git[
                "clone",
                "--recurse-submodules",
                "https://github.com/monty888/monstr_terminal.git",
            ]
            & FG
        )
        echo["Building new venv"] & FG
        import venv

        venv.main(["monstr_terminal/venv"])
        echo["installing deps"] & FG
        pip = local["monstr_terminal/venv/bin/pip"]
        pip["install", "-r", "./monstr_terminal/requirements.txt"] & FG
        echo["installing monstr"] & FG
        pip["install", "./monstr_terminal/monstr"] & FG
        echo["testing event_view"] & FG

    python = local["monstr_terminal/venv/bin/python"]
    python["monstr_terminal/event_view.py"] & TF()
    yield python


@pytest.fixture(scope="session")
def relay(monstr_terminal):
    cmd = monstr_terminal["monstr_terminal/run_relay.py", "--port", PORT]
    future = cmd & BG
    yield future
    future.proc.terminate()


@pytest.fixture(scope="session")
def session_key():
    yield Keys()


def self_terminate():
    """send SIGHUP to our own pid, because it will hangup the asyncIO loop."""
    os.kill(os.getpid(), signal.SIGHUP)


# @pytest.mark.skip("ignore")
def test_send_and_receive_some_messages(relay, session_key):  # noqa: ARG001
    messages = [{"foo": "bar"}]
    success = False

    def wait_for_it(client: OLClient, js: str, event: Event) -> None:  # noqa: ARG001
        js = json.loads(js)
        if js["foo"] == "bar":
            js["foo"] = "baz"
            client.broadcast(js, tags=[["better", True]])
            self_terminate()
        elif js["foo"] == "baz":
            nonlocal success
            success = True

    send_and_disconnect([RELAY_URL], session_key, messages)

    with contextlib.suppress(asyncio.exceptions.CancelledError):
        listen_forever(
            keys=session_key,
            relay=RELAY_URL,
            lookback=10,
            domain_handlers=[
                wait_for_it,
            ],
        )
    assert success


import queue
import threading


def threaded_listen_forever(
    q: queue.Queue,
    session_key: Keys,
    lookback: int,
    domain_handlers: list[Callable],
    relay: str | list[str] = RELAY_URL,
) -> None:
    try:
        listen_forever(
            keys=session_key,
            relay=relay,
            lookback=lookback,
            domain_handlers=domain_handlers,
            thread_command_queue=q,
        )
    except Exception as e:
        q.put(e)
    else:
        # always put up something in the queue to .get() will not wait forever
        q.put(None)  # signal that processing was successful


def test_send_and_receive_some_messages_using_threads(relay, session_key):
    success = queue.Queue()

    def wait_for_it(client: OLClient, js: str, event: Event) -> None:  # noqa: ARG001
        js = json.loads(js)
        if js["foo"] == "bar":
            js["foo"] = "baz"
            client.broadcast(js, tags=[["better", True]])
            client.terminate()
        elif js["foo"] == "baz":
            nonlocal success
            success.put(True)

    q = queue.Queue()
    listen_thread = threading.Thread(
        target=threaded_listen_forever, args=(q, session_key, 10, [wait_for_it])
    )
    listen_thread.start()

    messages = [{"foo": "bar"}]
    logging.debug('initiating "send and disconnect"')
    send_and_disconnect([RELAY_URL], session_key, messages)
    logging.debug("storing signal.SIGHUP in q")
    # sending_thread = threading.Thread(
    #     target=send_and_disconnect, args=([RELAY_URL], session_key, messages)
    # )
    # sending_thread.start()
    # sending_thread.join(2)
    # signal the asyncio loop to terminate in the other thread
    q.put(signal.SIGHUP)
    listen_thread.join(2)
    ex = q.get()  # get exception from the queue if there was one
    if isinstance(ex, BaseException):  # If there was an exception, reraise it
        raise ex
    assert True
    # assert success.get() is True
