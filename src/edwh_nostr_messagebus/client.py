import asyncio
import binascii
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

    def __repr__(self):
        shortid = "{:05x}".format(binascii.crc32(f"{id(self)}".encode()) & 0xFFFFFFFF)
        return (
            f"<OLClient:{shortid} k:{self.keys.private_key_hex()[:5]} {self.purpose} {','.join(_.__name__ for _ in self.domain_handlers)}>"
        )

    def __init__(
        self,
        *,
        relay: str,
        keys: Keys,
        domain_handlers: Iterable[Callable[["OLClient", js_str, Event], None]] = (),
        lookback: datetime.timedelta | None = None,
        private_kinds: Iterable[int] | DEFAULT = DEFAULT,
        anon_kinds: Iterable[int] | DEFAULT = DEFAULT,
        purpose: str = "?",
    ) -> None:
        """
        Initializes a new instance of the class, creates a new ClientPool as self.client.

        :type kinds: the kinds of messages to subscribe to, DEFAULT means 1,4, 1984 and 1985
        :param relay: The relay to be used.
        :param keys: The keys to be used.
        :param domain_handlers: The domain handlers to be used. Default is an empty iterable.
        :param lookback: The lookback duration to be used. Default is None.
        :param purpose: The purpose for this client, used for logging. Default is '?'.
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
        self.purpose = purpose

    def on_connect(self, client: Client) -> None:
        logging.debug(f"{self}: OLClient connected")
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
        logging.debug(f"{self}: OLClient subscribed")

    def do_event(self, client: Client, name: str, event: Event) -> None:  # noqa: ARG002
        """
        Calls all domain handlers with the response text and event. Called from monstr code when registered as handlers.

        :param client: The client object.
        :param name: The name of the event.
        :param event: The event object.
        :return: None.
        """
        logger.debug(f"{client}: do_event: {name} {event}")
        for handler in self.domain_handlers:
            try:
                logger.debug(f"{client}: {handler.__name__} {name} {event}")
                handler(self, self.get_response_text(event), event)
            except StopProcessingHandlers:
                logger.debug(f'{client}: caught StopProcessingHandlers')
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
        try:
            logging.info("--->")
            self.client.run()
            logging.info("<---")
        except Exception as e:
            logging.error(e)

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
            f'{self}: Broadcasting {payload!r} with {tags} {"public" if public else "privately"}'
        )
        logging.info(
            f'{self}: Broadcasting {payload!r} {"publicly" if public else "privately"}'
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
    logger.debug(f"{client}: Received exit signal {signal_.name}, commencing cleanup")

    # tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    #
    # logger.debug(f"{client}: found{len(tasks)} tasks")
    # logger.debug(f"{client}: requesting client to end")

    client.end()
    await asyncio.sleep(0.5)

    # logger.debug(f"{client}: cancelling all tasks")

    # for task in tasks:
    #     if not task.cancelled():
    #         logger.debug(f"Cancelling task {task}")
    #         with contextlib.suppress(RecursionError):
    #             task.cancel()
    # logger.debug(f"{client}: waiting for canceled tasks to finish:")
    # for task in tasks:
    #     logger.debug(f" - waiting for {task}")
    # #await asyncio.gather(*tasks, return_exceptions=True)
    logger.debug(f"{client}: marking cleanup done.")
    cleanup_done_event.put("cleanup done")


async def shutdown_on_signal(sig, loop, client: OLClient):
    logging.info(f"{client}: Received shutdown signal {sig}...")
    await asyncio.create_task(
        cleanup(sig, loop, client), name="cleanup after shutdown signal"
    )


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
        purpose="S&D",
    )
    messages_sent = asyncio.Event()

    # noinspection PyProtectedMember
    async def wait_for_empty_queue():
        """
        Wait until all queues are empty before disconnecting the client.

        :return: None
        """
        logger.debug(f"{client} Waiting for empty queue")
        if hasattr(client.client, "._publish_q"):
            logger.debug(f'{client}: ._publish_q peek')
            # when using a single relay, just use this.
            client_queues = [client.client._publish_q]
        else:
            logger.debug(f'{client}: .clients._clients[].client._publish_q peek')
            # when using multiple relays, work through the pool
            client_queues = [
                _["client"]._publish_q for _ in client.client._clients.values()
            ]


        logging.debug(
            f"{client} monitoring {len(client_queues)} queues if they are ready to quit: {client_queues}"
        )
        while total_open_connections := sum(_.qsize() for _ in client_queues):
            logging.debug(f"Waiting for connections ({total_open_connections}) to close.")
            for q in client_queues:
                logging.debug(f"> {q}")
            await asyncio.sleep(0.5)

        logging.debug(f"{client} requesting client to release the connection")
        client.end()
        logging.debug(f"{client} Marking messages as ready for close")
        messages_sent.set()

    async def connect_execute_and_die():
        """
        Connects to a relay, sends a set of messages, waits for them to be sent and terminates the connection.
        """
        logger.debug(f"{client}: Running client in new task ")
        client_task = asyncio.create_task(
            client_run_result:= client.run(), name=f"client.run of {client}"
        )
        logger.debug(f'client_run_result: {client_run_result!r}')
        logger.debug(f'client_task: {client_task!r}')
        await asyncio.sleep(0.5)
        logger.debug(f'client_task: {client_task!r}')
        logger.debug(f"{client}: New queue monitor ")
        stop_task = asyncio.create_task(
            wait_for_empty_queue(), name=f"wait_for_empty_queue related to {client}"
        )
        for message in messages:
            logger.info(f"{client}: sending message...")
            logger.debug(f"{client}: {message}")
            client.broadcast(message)
        # logger.debug(f"{client}: awaiting client")
        # await client_task
        # logger.debug(f"{client}: awaiting stopper: {stop_task!r}")
        # await stop_task
        logger.debug(f"{client}: waiting for signal from the empty queue monitor")
        await messages_sent.wait()
        logger.debug(f"{client}: starting cleanup")
        await cleanup(signal.SIGINT, asyncio.get_event_loop(), client)
        logger.debug(f"{client}: Waiting for cleanup done signal.")
        timeout = 5
        while timeout > 0:
            with contextlib.suppress(queue.Empty):
                evt = cleanup_done_event.get(block=False)
                logger.debug(
                    f"{client}: got a cleanup event done signal after {5 - timeout} seconds. "
                )
            timeout -= 0.3
            await asyncio.sleep(0.1)
        logger.debug(f"{client}: Done, returning from connect_execute_and_die")

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
    max_loop_duration:int|None = None
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
        purpose="Listen-4ever",
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
        logging.debug("Waiting for commands from the thread command queue.")
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(0.3)
            with contextlib.suppress(queue.Empty):
                command: signal.Signals = thread_command_queue.get(block=False)
                logging.debug(f"⚠️ received signal: {command}")
                if isinstance(command, signal.Signals):
                    logging.debug(f"Requesting shutdown for {client} in a new task")
                    shutdown_on_signal_task = asyncio.create_task(
                        shutdown_on_signal(command, loop, client),
                        name=f"Shutdown on signal for {client}",
                    )
                    logging.debug("terminating process_thread_command_queue itself")
                    thread_command_queue.task_done()
                    await shutdown_on_signal_task
                    return
                else:
                    logging.debug(f"🚫 uknown command: {command}")
                    thread_command_queue.task_done()
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
                        shutdown_on_signal(s, loop, client),
                        name=f"Shutdown on signal {s} for {client}",
                    ),
                )

        if thread_command_queue:
            # spawn a thread to monitor our thread-queue
            logging.debug("Spawning task for process_thread_command_queue")
            await asyncio.create_task(
                process_thread_command_queue(),
                name=f"Process thread command queue related to {client}",
            )
        # actually start a client.
        logging.debug(f"Running client {client}")
        await client.run()
        await asyncio.sleep(0.5) # waarom worden hier been berichten in gelezen?!?!?
        # logging.debug(f"Sending SIGINT to {client}")
        # await cleanup(signal.SIGINT, loop, client)
        if max_loop_duration:
            logging.info(f'max_loop_duration: {max_loop_duration}')
            timeout = max_loop_duration
            while timeout > 0:
                with contextlib.suppress(queue.Empty):
                    cleanup_done_event.get(block=False)
                    logging.debug(f"🧹 Got the cleanup done event in {5-timeout} seconds.!")
                    cleanup_done_event.task_done()
                    break
                timeout -= 0.1
                await asyncio.sleep(0.1)
            else:
                # only on timeout:
                client.end()
        else:
            logging.info('No max_loop_duration: perpetual mode')

    # fireup a loop
    # run the function that will start the tasks from within the loop
    asyncio.run(run_services(), debug=True)
