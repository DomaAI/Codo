# Contributing

Thanks for helping with Codo.

## Ground rules

- Codo is a single Python file (`codo`) with no third party dependencies. Keep it that way: standard library only, Python 3.9+.
- It has to work on Linux, macOS and Windows. If you touch the terminal, process or path code, say which systems you tested.
- Every behaviour change comes with a test in `tests/`. Tests must not use the network or call a model provider. Use the local fake `/v1` server and fake agents in `tests/test_codo_konta_agenci.py` as examples.
- Interface text goes through `_L("…")` or `_Lf("…", …)` with the Polish text as the key, and the English translation is added to the `_EN` table at the end of the file.

## Running tests

```bash
python3 -m py_compile codo
CODO_LANG=pl CODO_FILE=$PWD/codo python3 -m unittest discover -s tests
```

## Pull requests

- One topic per pull request, with a short description of what changes for the user.
- Add a line to `CHANGELOG.md` under an `Unreleased` heading.
- By sending a pull request you agree that your contribution is licensed under the Apache License 2.0.

## How releases work

The `codo` file in this repository is exported from MADD's main repository, where it is developed together with the DomaAI backend. Accepted pull requests are applied there and come back here with the next release, so the history of `codo` here is a series of release commits.
