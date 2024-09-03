# edwh-nostr-messagebus
[![PyPI - Version](https://img.shields.io/pypi/v/edwh-nostr-messagebus.svg)](https://pypi.org/project/edwh-nostr-messagebus)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/edwh-nostr-messagebus.svg)](https://pypi.org/project/edwh-nostr-messagebus)

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
- Install [`monstr_terminal`](https://pypi.org/project/monstr-terminal) using: 
  ```
  git clone https://github.com/monty888/monstr_terminal.git  
  cd monstr_terminal  
  python3 -m venv venv   
  source venv/bin/activate   
  pip install .
  ```
- Install py-invoke using `pip install invoke`
- Run `python3 ./run_relay --port 8888` from the `monstr_terminal` package to host a local relay in a separate terminal
- chdir to the examples folder (the one with the `tasks.py` file)
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


## Packaging
Make sure your commit messages are semantic. 

- `semantic-release publish; hatch build -c ; hatch publish` 