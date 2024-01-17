#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
  Simple json dump of the event viewer demonstrating
  how easy it is to play around with the events read
  from nostr without having to implement a full client.

    Usage when you use a config file:
        $ ./python3 event_view.py -o json | ./event_view_consumer.py

    or, if you want to use a specific  nostr relay instance:
        $ python3 event_view.py -r wss://nos.lol -o json | python3 event_view_consumer.py
"""

import sys
import signal
import asyncio
import datetime
import typing

import aioconsole
import fileinput
import json
import pprint
import os
from typing import Iterable, Any, Callable
from monstr.encrypt import Keys
from monstr.client.client import ClientPool, Client
from monstr.event.event import Event
from monstr.util import ConfigError
import logging


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
        self.client = Client(relay_url=self.relay,
                             on_auth=self.on_auth,
                             on_connect=self.on_connect if domain_handlers else None,
                             read=True,
                             write=True)
        self._all_clients.append(self.client)
        self.domain_handlers = domain_handlers

    def on_connect(self, client: Client) -> None:
        print('connected')
        client.subscribe(type(self).__name__,
                         handlers=[self],
                         filters=[{
                             'kinds': [Event.KIND_ENCRYPT, Event.KIND_TEXT_NOTE],
                             '#p': [self.keys.public_key_hex()],
                             'since': int((datetime.datetime.now() - self.lookback).timestamp())
                         }, {
                             'kinds': [Event.KIND_ENCRYPT,
                                       Event.KIND_TEXT_NOTE],
                             'since': int((datetime.datetime.now() - self.lookback).timestamp())
                         }]
                         )
        print('subscribed')

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
        print('on_auth')
        # noinspection PyTypeChecker
        client.auth(self.keys, challenge)

    async def run(self) -> typing.Awaitable:
        print('started!!')
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
        print('broadcast')
        if not public and not tags:
            raise ValueError('Cannot send encrypted messages without knowing the recipient.')

        n_event = Event(kind=Event.KIND_TEXT_NOTE if public else Event.KIND_ENCRYPT,
                        content=json.dumps(payload),
                        pub_key=self.keys.public_key_hex(),
                        tags=tags)
        n_event.sign(self.keys.private_key_hex())
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
