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
from client import OLClient
import datetime
import logging


class ConfigurationError(Exception): pass


class Config:
    relay = os.getenv('NOSTR_RELAY', 'ws://127.0.0.1:8888')
    private_key = os.getenv('NOSTR_PRIVKEY')
    # convert the nsec private key to Key object or createa a new keypair using Keys()
    keys = Keys(private_key) if private_key else Keys()


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


def clean_exit(clients: list[OLClient]) -> None:
    # exit cleanly on ctrl c
    def sigint_handler(signal, frame):
        print('stopping...')
        for olclient in clients:
            olclient.end()
        exit(0)

    signal.signal(signal.SIGINT, sigint_handler)


def parse_key(keyname_or_bech32: str | None) -> Keys:
    if keyname_or_bech32 is None:
        # in the case of None, always the privkey in the dotenv
        try:
            return parse_key(edwh.read_dotenv()['PRIVKEY'])
        except KeyError:
            raise ConfigurationError('PRIVKEY not found in .env, try running `inv setup`. ')
    try:
        return Keys(keyname_or_bech32)
    except:
        return Keys(edwh.read_dotenv()[keyname_or_bech32.upper()])


# Create a simple function that will send new messages every several seconds
@task(iterable=['gidname'], positional=['gidname'],
      help={'gidname': "formatted as 'gid:name', can be used multiple times", 'key': '(friendly) private key'})
def new(ctx, gidname, key=None):
    """
    Simulates a new object and sends the message over the relay,
    waiting for the client to finish all events and closes the connection.
    """
    keys = parse_key(key)
    logging.basicConfig(level=logging.INFO)
    env = edwh.read_dotenv()
    client = OLClient(
        relay=env['RELAY'],
        keys=keys,
        domain_handlers=[],
    )
    clean_exit([client])

    async def wait_for_empty_queue():
        while client.client._publish_q.qsize():
            await asyncio.sleep(0.1)
        print('requesting end')
        client.end()

    async def connect_and_obey():
        # print('running client')
        client_task = await asyncio.create_task(client.run())
        # print('client is running, broadcasting')
        for _ in gidname:
            gid, name = _.split(':')
            client.broadcast(dict(gid=gid, name=name))
        # print('post create task')
        stop_task = asyncio.create_task(wait_for_empty_queue())
        dir(stop_task)
        # print('waiting to complete')
        await client_task
        # print('awaiting stop task')
        await stop_task

    asyncio.run(connect_and_obey())


@task()
def connect(context, key=None):
    """
    Connect to the relay, listening for messages.
    """
    logging.basicConfig(level=logging.INFO)
    keys = parse_key(key)
    env = edwh.read_dotenv()
    client = OLClient(
        relay=env['RELAY'],
        lookback=datetime.timedelta(seconds=int(env['LOOKBACK'])),
        keys=keys,
        domain_handlers=[print_friendly_keyname_handler, print_event_handler],
    )

    clean_exit([client])

    async def run_services():
        await asyncio.create_task(await client.run())

    asyncio.run(run_services())


@task()
def key(context, name=None):
    """
    Manage key aliases in the .env file. Proposes a new key for unknown entries, always returns prints the value.
    """
    keys = Keys()
    if name:
        bech32 = edwh.check_env(name.upper(), default=keys.private_key_bech32(), comment=f'Fresh key for {name}:')
        print(bech32)
