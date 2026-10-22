"""Miliastra Wonderland Editor bridge.

Interface-first component (see ``docs/research-plan/60-interface-contracts.md``).
This package implements a *minimal real* subset of the proposed ``mw.*`` contract:
one stdin-JSON to stdout-JSON process, three methods, and no game automation.

Design limits that are enforced in code, not just documented:

* the project is this directory, derived from ``__file__`` -- never from cwd;
* only two frozen, verified executables may ever be started;
* no UI automation, no code injection, no window messages, no shell;
* a process launch is never reported as "sandbox ready".
"""

BRIDGE_VERSION = "0.1.0"
