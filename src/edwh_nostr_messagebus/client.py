import asyncio
import contextlib
import datetime
import json
import logging
import queue
import signal
import typing
from collections.abc import Callable, Iterable
from queue import Queue
from typing import Any

from monstr.client.client import Client, ClientPool
from monstr.encrypt import Keys
from monstr.event.event import Event

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler = logging.FileHandler("troubleshooting.log")
handler.setFormatter(formatter)
logger.addHandler(handler)


# JSON source string
js_str: typing.TypeAlias = str


class DEFAULT:
    pass


class StopProcessingHandlers(StopIteration):
    pass


class OLClient:
    """
    OLClient class for interacting with the Nostr message bus.

    Attributes:
        client (Client | ClientPool): The client or client pool used for communication with the Nostr message bus.
        keys (Keys): The keys used for authentication and encryption.
        _all_clients (list): A list to store all the clients for Ctrl-C handlers.
        domain_handler (list[Callable[[str, Event], None]]): A list of domain handlers.

    Methods:
        __init__(self, relay: str, keys: Keys, domain_handlers: Iterable[Callable[[str, Event], None]] = (),
                 lookback: datetime.timedelta | None = None) -> None:
            Initializes the OLClient instance.

        on_connect(self, client: Client) -> None:
            Event handler for client connection.

        do_event(self, client: Client, name: str, event: Event) -> None:
            Processes an event received from the Nostr message bus.

        get_response_text(self, event: Event) -> str:
            Returns the response text for an event.

        on_auth(self, client: Client, challenge: str) -> None:
            Authenticates the client with the challenge.

        run(self) -> typing.Awaitable:
            Runs the OLClient event loop.

        end(self) -> None:
            Stops the OLClient event loop.

        broadcast(self, payload: Any, tags: Iterable[str] = (), public: bool = True) -> None:
            Broadcasts a message to the Nostr message bus.

        direct(self, to_keys: Keys, payload: Any, tags: Iterable[str] = ()) -> None:
            Sends a direct message to the specified recipient.
    """

    client: Client | ClientPool
    keys: Keys
    # list to store the clients in for ctrl c handlers
    _all_clients: typing.ClassVar = []
    domain_handler: Iterable[Callable[["OLClient", js_str, Event], None]]

    def __init__(
        self,
        *,
        relay: str,
        keys: Keys,
        domain_handlers: Iterable[Callable[["OLClient", js_str, Event], None]] = (),
        lookback: datetime.timedelta | None = None,
        private_kinds: Iterable[int] | DEFAULT = DEFAULT,
        anon_kinds: Iterable[int] | DEFAULT = DEFAULT,
    ) -> None:
        """
        Initializes a new instance of the class, creates a new ClientPool as self.client.

        :type kinds: the kinds of messages to subscribe to, DEFAULT means 1,4, 1984 and 1985
        :param relay: The relay to be used.
        :param keys: The keys to be used.
        :param domain_handlers: The domain handlers to be used. Default is an empty iterable.
        :param lookback: The lookback duration to be used. Default is None.

        """
        self.relay = relay
        self.keys = keys
        self.lookback = lookback or datetime.timedelta(0)
        self.private_kinds = (
            [Event.KIND_ENCRYPT, Event.KIND_TEXT_NOTE]
            if private_kinds is DEFAULT
            else private_kinds
        )
        self.anon_kinds = (
            [Event.KIND_TEXT_NOTE, 1984, 1985] if anon_kinds is DEFAULT else anon_kinds
        )
        self.client = ClientPool(
            clients=[relay] if isinstance(relay, str) else relay,
            on_auth=self.on_auth,
            on_connect=self.on_connect if domain_handlers else None,
            read=True,
            write=True,
        )
        self._all_clients.append(self.client)
        self.domain_handlers = domain_handlers

    def on_connect(self, client: Client) -> None:
        logging.debug("OLClient connected")
        # filters can be alist of dicts, meaning they are ORed.
        # the first filters direct messages to this pubkey (plaintext and encrypted text notes)
        # the second reads all unencrypted text-notes from everyone, that the relay allows us to read.
        client.subscribe(
            type(self).__name__,
            handlers=[self],
            filters=[
                {
                    "kinds": self.private_kinds,
                    "#p": [self.keys.public_key_hex()],
                    "since": int(
                        (
                            datetime.datetime.now(datetime.UTC) - self.lookback
                        ).timestamp()
                    ),
                },
                {
                    "kinds": self.anon_kinds,
                    "since": int(
                        (
                            datetime.datetime.now(datetime.UTC) - self.lookback
                        ).timestamp()
                    ),
                },
            ],
        )
        logging.debug("OLClient subscribed")

    def do_event(self, client: Client, name: str, event: Event) -> None:  # noqa: ARG002
        """
        Calls all domain handlers with the response text and event. Called from monstr code when registered as handlers.

        :param client: The client object.
        :param name: The name of the event.
        :param event: The event object.
        :return: None.
        """
        for handler in self.domain_handlers:
            try:
                handler(self, self.get_response_text(event), event)
            except StopProcessingHandlers:
                break
            except Exception as e:
                logger.error(e)
                raise

    def get_response_text(self, event: Event) -> js_str:
        """
        Returns the response text possibly decrypting the content if it's a nip-4 encrypted message.

        :param event: an instance of the Event class representing the event
        :type event: Event
        :return: the response text
        :rtype: str
        """
        return (
            event.decrypted_content(
                priv_key=self.keys.private_key_hex(), pub_key=event.pub_key
            )
            if event.kind == Event.KIND_ENCRYPT
            else event.content
        )

    def on_auth(self, client: Client, challenge: str):
        """Sign the challenge with the keys to authorize the client."""
        logging.info("OLClient authenticating")
        # noinspection PyTypeChecker
        client.auth(self.keys, challenge)

    async def run(self) -> typing.Awaitable:
        """Pass-thru to the client's run method."""
        return self.client.run()

    def end(self) -> None:
        """Pass-thru to the client's end method."""
        self.client.end()

    def broadcast(
        self,
        payload: Any | Event,
        tags: Iterable[Iterable[str | Any]] | str = (),
        *,
        public: bool = True,
    ):
        """
        Broadcasts a message to the Nostr message bus.

        Args:
            payload: The payload to be broadcasted, either a prefilled Event or an Event instance
            tags: Optional iterable of tags associated with the payload.
            public: Flag indicating whether the message should be public or encrypted.

        Returns:
            None

        Raises:
            ValueError: If `public` is False and no tags are provided.

        Note:
            If `public` is True, the message will be a public text note.
            If `public` is False, the message will be encrypted and require tags indicating the recipient.
            The payload will be converted to a JSON string and signed with the client's private key before publishing.
        """
        if not public and not tags:
            raise ValueError(
                "Cannot send encrypted messages without knowing the recipient."
            )
        if isinstance(payload, Event):
            n_event = payload
        else:
            n_event = Event(
                kind=Event.KIND_TEXT_NOTE if public else Event.KIND_ENCRYPT,
                content=json.dumps(payload),
                pub_key=self.keys.public_key_hex(),
                tags=tags,
            )
        n_event.sign(self.keys.private_key_hex())
        logging.debug(
            f'Broadcasting {payload!r} with {tags} {"public" if public else "privately"}'
        )
        logging.info(
            f'Broadcasting {payload!r} {"publicly" if public else "privately"}'
        )
        self.client.publish(n_event)

    def direct(self, to_keys: Keys, payload: Any, tags: Iterable[str] = ()):
        """
        Sends a direct message to the specified recipient.

        Args:
            self: The instance of the client.
            to_keys: The `Keys` object representing the recipient's public and private keys.
            payload: The payload to be sent.
            tags: Optional iterable of tags associated with the payload.

        Returns:
            None

        Note:
            The `tags` will be modified to include a tag indicating the recipient's public key.
            The payload will be broadcasted using the `broadcast` method of the client.
        """
        tags = [["p", to_keys.public_key_hex()]] + list(tags)
        self.broadcast(payload, tags)


cleanup_done_event = queue.Queue()


async def cleanup(signal_, loop, client: OLClient):
    print(f"Received exit signal {signal_.name}...")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]

    client.end()

    await asyncio.sleep(0.5)

    # TODO  alleen task parents killen en niet de children.

    for task in tasks:
        if not task.cancelled():
            task.cancel()

    print("Cancelling tasks, waiting for them to finish...")
    await asyncio.gather(*tasks, return_exceptions=True)
    print("Tasks finished cancelling.")
    cleanup_done_event.put("cleanup done")


async def shutdown_on_signal(sig, loop, client: OLClient):
    print(f"Received shutdown signal {sig}...")
    await cleanup(sig, loop, client)


def send_and_disconnect(
    relay: str | list[str], keys: Keys, messages: list[dict[str, str] | Event]
):
    """
    This method establishes a connection with the specified relay(s) using the provided keys, sends the given messages,
    and then disconnects from the relay(s). It uses the OLClient class to handle the communication with the relay(s).

    Example usage:
        relay = "example.com"
        keys = Keys(...)
        messages = [
            {"id": "1", "text": "Hello, world!"},
            {"id": "2", "text": "Goodbye, world!"}
        ]

        send_and_disconnect(relay, keys, messages)

    :param relay: The relay(s) to use for sending the messages. It can be specified as a string or a list of strings.
    :param keys: The keys to use for authentication with the relay(s).
    :param messages: The list of messages to send. Each message should be a dictionary of key-value pairs.
    :return: None
    """
    client = OLClient(
        relay=relay,
        keys=keys,
        domain_handlers=[],
    )

    async def wait_for_empty_queue():
        """
        Wait until all queues are empty before disconnecting the client.

        :return: None
        """
        if hasattr(client.client, "._publish_q"):
            client_queues = [client.client._publish_q]
        else:
            client_queues = [
                _["client"]._publish_q for _ in client.client._clients.values()
            ]

        logging.debug(
            f"monitoring {len(client_queues)} queues if they are ready to quit"
        )
        while total_open_connections := sum(_.qsize() for _ in client_queues):
            logging.debug(f"Waiting for {total_open_connections} to close.")
            await asyncio.sleep(0.3)

        logging.debug("requesting client to release the connection")
        client.end()

    async def connect_execute_and_die():
        """
        Connects to a relay, sends a set of messages, waits for them to be sent and terminates the connection.
        """
        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            # noinspection PyUnresolvedReferences
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown_on_signal(s, loop, client))
            )

        client_task = await asyncio.create_task(client.run())
        for message in messages:
            client.broadcast(message)
        await wait_for_empty_queue()
        await client_task
        await cleanup(signal.SIGINT, loop, client)
        timeout = 5
        while timeout > 0:
            with contextlib.suppress(queue.Empty):
                cleanup_done_event.get(block=False)
            timeout -= 0.1
            await asyncio.sleep(0.1)

    asyncio.run(connect_execute_and_die())


def listen_forever(
    *,
    keys: Keys,
    relay: list[str] | str,
    lookback: int = 0,
    domain_handlers: Iterable[Callable[[OLClient, str, Event], None]] = (),
    anon_kinds: Iterable[int] | DEFAULT = DEFAULT,
    private_kinds: Iterable[int] | DEFAULT = DEFAULT,
        thread_command_queue: Queue = None,
):
    """
    Start listening for events indefinitely, except when thread_command_queue is a queue and a signal.signal
    object is sent to "emulate" a signal.SIGINT or similar.

    :param anon_kinds: the kind of notes to subscribe to without specific key
    :param private_kinds: the kind of notes to subscribe to when addressed over public key
    :param keys: The keys used for authentication.
    :param relay: The relay(s) to connect to. It can be a single relay as a string or a list of relays.
    :param lookback: The number of seconds to look back for events.
    :param domain_handlers: A collection of domain handlers to handle specific event domains.
    :param thread_command_queue: set a queue.Queue when using a separate thread, avoiding signal handler registration.
    :return: None
    """
    client = OLClient(
        relay=relay,
        lookback=datetime.timedelta(seconds=lookback),
        keys=keys,
        domain_handlers=domain_handlers,
        anon_kinds=anon_kinds,
        private_kinds=private_kinds,
    )

    async def process_thread_command_queue():
        """
        Process commands from the thread command queue.

        This function continuously retrieves commands from the thread
        command queue and processes them. The commands are expected to
        be instances of the `signal.signal` class. When a command is
        received, it is passed to the `shutdown_on_signal` function
        along with the event loop and client.

        This function also includes a 0.3-second delay between command
        processing to avoid excessive CPU usage.

        :return: None
        """
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(0.3)
            with contextlib.suppress(queue.Empty):
                command: signal.Signals = thread_command_queue.get(block=False)
                if isinstance(command, signal.Signals):
                    await shutdown_on_signal(command, loop, client)
                    return

    async def run_services():
        loop = asyncio.get_event_loop()
        if not thread_command_queue:
            # only perform this in the main thread, as signals cannot be handled in new threads.
            signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
            for s in signals:
                # noinspection PyUnresolvedReferences
                loop.add_signal_handler(
                    s,
                    lambda s=s: asyncio.create_task(
                        shutdown_on_signal(s, loop, client)
                    ),
                )

        if thread_command_queue:
            # spawn a thread to monitor our thread-queue
            await asyncio.create_task(process_thread_command_queue())
        # actually start a client.
        await client.run()
        await cleanup(signal.SIGINT, loop, client)
        timeout = 5
        while timeout > 0:
            with contextlib.suppress(queue.Empty):
                cleanup_done_event.get(block=False)
            timeout -= 0.1
            await asyncio.sleep(0.1)

    # fireup a loop
    # run the function that will start the tasks from within the loop
    asyncio.run(run_services())
