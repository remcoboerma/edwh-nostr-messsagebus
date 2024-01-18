import copy
import datetime
import json
import logging
import pprint
import uuid

import edwh
from invoke import task
from monstr.encrypt import Keys
from monstr.event.event import Event

from edwh_nostr_messagebus.client import send_and_disconnect, listen_forever, OLClient


class ConfigurationError(Exception):
    pass


@task()
def setup(ctx):
    """
    This function is a task that sets up the environment for the application.
    It checks the values of certain environment variables and ensures they are properly set.
    """
    edwh.check_env("RELAY", "ws://127.0.0.1:8888", "What NOSTR relay to connect to")
    edwh.check_env(
        "PRIVKEY", Keys().private_key_bech32(), "Default privkey when none specified"
    )
    edwh.check_env(
        "LOOKBACK",
        "0",
        "How many seconds to look back for messages when listening to nostr.",
    )
    for keyname in [
        "platform-a",
        "platform-b",
        "slo",
        "nsmv",
        "producer-a",
        "producer-b",
    ]:
        edwh.check_env(
            keyname.upper(),
            Keys().private_key_bech32(),
            f"this demo needs keys for identity {keyname}",
        )


def pprint_handler(client: OLClient, js: str, event: Event) -> None:
    """
    Pretty prints the JSON contents of the event, for troubleshooting business events.

    :param js: The JSON contents to be pretty printed.
    :param event: The event related to the pprint_handler method.
    :return: None
    """
    pprint.pprint(json.loads(js), indent=2, width=120, sort_dicts=True)


def print_event_handler(client: OLClient, js: str, event: Event) -> None:
    """
    Prints the objects using pprinted reprs, for troubleshooting nostr events.
    """
    e = copy.copy(event.__dict__)
    e['_tags'] = dict(event.tags.tags)
    e = {k.strip('_'):v for k,v in e.items()}
    if 'meta' in e['tags']:
        e['tags']['meta'] = json.loads(e['tags']['meta'])
    e['created_at'] = str(datetime.datetime.fromtimestamp(e['created_at']))
    e['sig'] = e['sig'][:10] + '...' + e['sig'][-10:]
    pprint.pprint(e, indent=2, width=120, sort_dicts=True)


def print_friendly_keyname_handler(client: OLClient, js: str, event: Event) -> None:
    """
    Print friendly keynames handler in a banner before the next handler fires, based on the .env file.
    """

    def pubkey_from_privkey(privkey: str) -> str | None:
        """
        Get the public key hex representation from a given private key.

        :param privkey: The private key in string format.
        :return: The public key hex representation if successful, otherwise None.
        """
        try:
            return Keys(privkey).public_key_hex()
        except Exception as e:
            return

    haystack = {
        pubkey_from_privkey(value): key for key, value in edwh.read_dotenv().items()
    }
    needle = event._pub_key.lower()
    name_or_key = haystack.get(needle, needle)
    print(f"---[from: {name_or_key}]-------------")


def parse_key(keyname_or_bech32: str | None) -> Keys:
    """
    Parse the given `keyname_or_bech32` and return the corresponding `Keys` object.

    :param keyname_or_bech32: The name or bech32 encoded key. If `None`, it retrieves the private key from the dotenv.
    :type keyname_or_bech32: str or None
    :return: The parsed `Keys` object.
    :rtype: Keys
    :raises ConfigurationError: If `keyname_or_bech32` is `None` and `PRIVKEY` is not found in the .env file.
    """
    if keyname_or_bech32 is None:
        # in the case of None, always the privkey in the dotenv
        try:
            return parse_key(edwh.read_dotenv()["PRIVKEY"])
        except KeyError as e:
            raise ConfigurationError(
                "PRIVKEY not found in .env, try running `inv setup`. "
            ) from e
    try:
        return Keys(keyname_or_bech32)
    except Exception:
        return Keys(edwh.read_dotenv()[keyname_or_bech32.upper()])


# Create a simple function that will send new messages every several seconds
@task(
    iterable=["gidname"],
    positional=["gidname"],
    help={
        "gidname": "formatted as 'gid:name', can be used multiple times",
        "key": "(friendly) private key",
    },
    incrementable="verbose",
)
def new(ctx, gidname, key=None, verbose=1):
    """
    Simulates a new object and sends the message over the relay,
    waiting for the client to finish all events and closes the connection.
    """
    logging.basicConfig(level=logging.CRITICAL - 10 * verbose)

    env = edwh.read_dotenv()
    relay = env["RELAY"]
    keys = parse_key(key or env["PRIVKEY"])
    messages = [
        {"gid": gid, "name": name} for gid, name in [_.split(":") for _ in gidname]
    ]
    send_and_disconnect(relay, keys, messages)


@task(
    incrementable="verbose",
)
def jstagtest(ctx, key=None, verbose=1):
    """
    """
    logging.basicConfig(level=logging.CRITICAL - 10 * verbose)

    env = edwh.read_dotenv()
    relay = env["RELAY"]
    keys = parse_key(key or env["PRIVKEY"])
    messages = [Event(
        kind=Event.KIND_TEXT_NOTE,
        content='Menselijke beschrijving',
        pub_key=keys.public_key_hex(),
        tags=[['olgid',f'gid://edwh/{uuid.uuid4()}'],
              ['meta',json.dumps(dict(hier='komt_wat',informatie='in die',nested=dict(kan='zijn',maar='dat hoeft niet',exl='!')))]]
    )]
    send_and_disconnect(relay, keys, messages)




@task(incrementable=["verbose"])
def connect(context, key=None, verbose=1):
    """
    Connect to the relay, listening for messages printing friendly names and message values.
    """
    logging.basicConfig(level=logging.CRITICAL - 10 * verbose)
    keys = parse_key(key)
    env = edwh.read_dotenv()
    listen_forever(
        keys,
        env["RELAY"],
        int(env["LOOKBACK"]),
        domain_handlers=[
            print_friendly_keyname_handler,
            print_event_handler,
        ],
    )


@task(incrementable=["verbose"])
def camelcaser(context, key=None, verbose=1):
    """
    Connect to the relay, listening for messages printing friendly names and message values.
    """
    logging.basicConfig(level=logging.CRITICAL - 10 * verbose)
    keys = parse_key(key)
    env = edwh.read_dotenv()

    def camelcase_name_handler(client: OLClient, js: str, event: Event) -> None:
        js = json.loads(js)
        if (better_name := js["name"].capitalize()) != js["name"]:
            # republish using a captialized name
            logging.info(
                f'Camelcasing {js["name"]} to {better_name} for messageid:{event._id}'
            )
            js["name"] = better_name
            client.broadcast(js, tags=[["better", True]])

    listen_forever(
        keys,
        env["RELAY"],
        int(env["LOOKBACK"]),
        domain_handlers=[
            camelcase_name_handler,
        ],
    )


@task()
def key(context, name=None):
    """
    Manage key aliases in the .env file. Proposes a new key for unknown entries, always returns prints the value.
    """
    keys = Keys()
    if name:
        bech32 = edwh.check_env(
            name.upper(),
            default=keys.private_key_bech32(),
            comment=f"Fresh key for {name}:",
        )
        print(bech32)
