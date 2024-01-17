#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import datetime
import json
import signal
import typing
from typing import Iterable, Any, Callable
import logging

from monstr.client.client import ClientPool, Client
from monstr.encrypt import Keys
from monstr.event.event import Event


class OLClient:
    client: Client | ClientPool
    keys: Keys
    # list to store the clients in for ctrl c handlers
    _all_clients = []
    domain_handler: list[Callable[[str, Event], None]]

    def __init__(self, relay: str, keys: Keys,
                 domain_handlers: Iterable[Callable[[str, Event], None]] = (),
                 lookback: datetime.timedelta | None = None
                 ) -> None:
        self.relay = relay
        self.keys = keys
        self.lookback = lookback or datetime.timedelta(0)
        self.client = ClientPool(clients=[self.relay],
                             on_auth=self.on_auth,
                             on_connect=self.on_connect if domain_handlers else None,
                             read=True,
                             write=True)
        self._all_clients.append(self.client)
        self.domain_handlers = domain_handlers

    def on_connect(self, client: Client) -> None:
        logging.debug('OLClient connected')
        # filters can be alist of dicts, meaning they are ORed.
        # the first filters direct messages to this pubkey (plaintext and encrypted text notes)
        # the second reads all unencrypted text-notes from everyone, that the relay allows us to read.
        client.subscribe(type(self).__name__,
                         handlers=[self],
                         filters=[{
                             'kinds': [Event.KIND_ENCRYPT, Event.KIND_TEXT_NOTE],
                             '#p': [self.keys.public_key_hex()],
                             'since': int((datetime.datetime.now() - self.lookback).timestamp())
                         }, {
                             'kinds': [Event.KIND_TEXT_NOTE],
                             'since': int((datetime.datetime.now() - self.lookback).timestamp())
                         }]
                         )
        logging.debug('OLClient subscribed')

    def do_event(self, client: Client, name: str, event: Event) -> None:
        for handler in self.domain_handlers:
            try:
                handler(self.get_response_text(event), event)
            except Exception as e:
                print(e)
                raise

    def get_response_text(self, event: Event) -> str:
        # possible parse this text also before passing onm
        return event.content if event.kind == Event.KIND_TEXT_NOTE else Event.decrypted_content(
            priv_key=self.keys.private_key_hex(), pub_key=event.pub_key)

    def on_auth(self, client: Client, challenge: str):
        """Sign the challenge with the keys to authorize the client."""
        logging.info('OLClient authenticating')
        # noinspection PyTypeChecker
        client.auth(self.keys, challenge)

    async def run(self) -> typing.Awaitable:
        return self.client.run()

    def end(self) -> None:
        self.client.end()

    def broadcast(self, payload: Any, tags: Iterable[str] = (), public: bool = True):
        """
        Broadcasts a message to the Nostr message bus.

        Args:
            payload: The payload to be broadcasted.
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
            raise ValueError('Cannot send encrypted messages without knowing the recipient.')

        n_event = Event(kind=Event.KIND_TEXT_NOTE if public else Event.KIND_ENCRYPT,
                        content=json.dumps(payload),
                        pub_key=self.keys.public_key_hex(),
                        tags=tags)
        n_event.sign(self.keys.private_key_hex())
        logging.debug(f'Broadcasting {json.dumps(payload)} with {tags} {"public" if public else "privately"}')
        logging.info(f'Broadcasting {repr(payload)} {"publicly" if public else "privately"}')
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
        tags = [['p', to_keys.public_key_hex()]] + list(tags)
        self.broadcast(payload, tags)


cleanup_done_event = asyncio.Event()


async def cleanup(signal_, loop, client:OLClient):
    print(f"Received exit signal {signal_.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    client.end()

    await asyncio.sleep(0.5)

    for task in tasks:
        task.cancel()

    print("Cancelling tasks, waiting for them to finish...")
    await asyncio.gather(*tasks, return_exceptions=True)
    print("Tasks finished cancelling.")
    cleanup_done_event.set()


async def shutdown_on_signal(sig, loop, client:OLClient):
    print(f"Received shutdown signal {sig}...")
    await cleanup(sig, loop, client)


def send_and_disconnect(relay: str | list[str], keys: Keys, messages: list[dict[str, str]]):
    """
    Sends messages over the relay, waits for the client to finish all events,
    and closes the connection.
    """
    logging.basicConfig(level=logging.DEBUG)
    client = OLClient(
        relay=relay,
        keys=keys,
        domain_handlers=[],
    )

    async def wait_for_empty_queue():
        if hasattr(client.client, '._publish_q'):
            client_queues = [client.client._publish_q]
        else:
            client_queues = [_['client']._publish_q for _ in client.client._clients.values()]

        logging.debug(f'monitoring {len(client_queues)} queues if they are ready to quit')
        while total_open_connections := sum(_.qsize() for _ in client_queues):
            logging.debug(f'Waiting for {total_open_connections} to close.')
            await asyncio.sleep(0.3)

        logging.debug('requesting client to release the connection')
        client.end()

    async def connect_execute_and_die():

        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown_on_signal(s, loop, client)))


        client_task = await asyncio.create_task(client.run())
        for message in messages:
            client.broadcast(message)
        stop_task = asyncio.create_task(wait_for_empty_queue())
        await client_task
        await stop_task
        cleanup_done_event.set()
        await cleanup_done_event.wait()

    asyncio.run(connect_execute_and_die())


def listen_forever(keys:Keys, relay:list[str]|str, lookback:int=0, domain_handlers:Iterable[Callable[[str, Event], None]] = ()):
    """
    Connect to the relay, listening for messages.
    """
    logging.basicConfig(level=logging.INFO)
    client = OLClient(
        relay=relay,
        lookback=datetime.timedelta(seconds=lookback),
        keys=keys,
        domain_handlers=domain_handlers,
    )

    async def run_services():
        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown_on_signal(s, loop, client)))

        await asyncio.create_task(await client.run())

        cleanup_done_event.set()
        await cleanup_done_event.wait()



    asyncio.run(run_services())