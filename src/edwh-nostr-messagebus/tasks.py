import asyncio
import copy
import fileinput
import signal
from asyncio import TaskGroup
from pathlib import Path
from uuid import UUID

from invoke import task
import json
import pprint
import os
import edwh
from typing import Iterable, Any
from monstr.encrypt import Keys
from monstr.client.client import ClientPool, Client
from monstr.event.event import Event
from client import OLClient, send_and_disconnect, listen_forever
import datetime
import logging


class ConfigurationError(Exception): pass


@task()
def setup(ctx):
    edwh.check_env('RELAY', 'ws://127.0.0.1:8888', 'What NOSTR relay to connect to')
    edwh.check_env('PRIVKEY', Keys().private_key_bech32(), 'What NOSTR relay to connect to')
    edwh.check_env('LOOKBACK', '0', 'How many seconds to look back for messages when listening to nostr.')


def pprint_handler(js: str, event: Event) -> None:
    pprint.pprint(json.loads(js), indent=2, width=120, sort_dicts=True)


def print_event_handler(js: str, event: Event) -> None:
    e = copy.copy(event.__dict__)
    e['_tags'] = copy.copy(event._tags.__dict__)
    pprint.pprint(e, indent=2, width=120, sort_dicts=True)


def print_friendly_keyname_handler(js: str, event: Event) -> None:
    def pubkey_from_privkey(privkey: str) -> str | None:
        try:
            return Keys(privkey).public_key_hex()
        except Exception as e:
            return

    haystack = {pubkey_from_privkey(value): key for key, value in edwh.read_dotenv().items()}
    needle = event._pub_key.lower()
    name_or_key = haystack.get(needle, needle)
    print(f'---[from: {name_or_key}]-------------')




def parse_key(keyname_or_bech32: str | None) -> Keys:
    if keyname_or_bech32 is None:
        # in the case of None, always the privkey in the dotenv
        try:
            return parse_key(edwh.read_dotenv()['PRIVKEY'])
        except KeyError as e:
            raise ConfigurationError(
                'PRIVKEY not found in .env, try running `inv setup`. '
            ) from e
    try:
        return Keys(keyname_or_bech32)
    except Exception:
        return Keys(edwh.read_dotenv()[keyname_or_bech32.upper()])


# Create a simple function that will send new messages every several seconds
@task(iterable=['gidname'], positional=['gidname'],
      help={'gidname': "formatted as 'gid:name', can be used multiple times", 'key': '(friendly) private key'})
def new(ctx, gidname, key=None):
    """
    Simulates a new object and sends the message over the relay,
    waiting for the client to finish all events and closes the connection.
    """
    logging.basicConfig(level=logging.DEBUG)

    env = edwh.read_dotenv()
    relay = env['RELAY']
    keys = parse_key(key or env['PRIVKEY'])
    messages = [{'gid': gid, 'name': name} for gid, name in [_.split(':') for _ in gidname]]
    send_and_disconnect(relay, keys, messages)


@task()
def connect(context, key=None):
    """
    Connect to the relay, listening for messages.
    """
    logging.basicConfig(level=logging.DEBUG)
    keys = parse_key(key)
    env = edwh.read_dotenv()
    listen_forever(keys, env['RELAY'], int(env['LOOKBACK']),
                   domain_handlers=[print_friendly_keyname_handler, print_event_handler])



@task()
def key(context, name=None):
    """
    Manage key aliases in the .env file. Proposes a new key for unknown entries, always returns prints the value.
    """
    keys = Keys()
    if name:
        bech32 = edwh.check_env(name.upper(), default=keys.private_key_bech32(), comment=f'Fresh key for {name}:')
        print(bech32)
