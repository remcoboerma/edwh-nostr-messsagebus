# .

[![PyPI - Version](https://img.shields.io/pypi/v/-.svg)](https://pypi.org/project/-)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/-.svg)](https://pypi.org/project/-)

-----

**Table of Contents**
- [Installation](#installation)
- [Usage](#usage)
- [License](#license)

## Installation

```console
pip install edwh-nostr-messagebus 
```

There is an example folder that you can [view on github](https://github.com/educationwarehouse/edwh-nostr-messagebus/tree/main/examples) 
with a helpful `tasks.py` demo to work with this library. 

## Usage
- Run `python3 ./run_relay --port 8888` from the `monstr_terminal` package to have local relay
- chdir to the examples folder (there is a tasks.py file there)
- Run `invoke setup` before anything else, in this folder, or wherever you create your `tasks.py`
- Run `invoke camelcaser -vv` to enable the example camelcaser bot 
- Run `invoke connect -vvv` to watch debug output from several read-only message dumping handlers
- Run `invoke new --gidname "abc:here is my test" --gidname "def:And another" --key edwh` to create 2 messages for new items

The first message from the `new` command will result in a trigger of the `camelcaser` since it's triggered by 
not camelcased names. The second message is "properly" formatted, and will not trigger it. In the debug view you can see
there are extra tags on the newly created message for the same gid, and an updated name attribute. 

Basically, this is alot of what this entire project is all about. 

## License

`-` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
