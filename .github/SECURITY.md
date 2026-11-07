# Security

## Reporting a problem

Please report security problems privately, through **Report a vulnerability** on the repository's
[Security tab](https://github.com/kanggu12/openDMTQ/security), not in an issue. Say what an attacker can do, on which
kind of install (Docker Compose, Kubernetes, host install, Windows bundle), and how to reproduce it. You will get an
answer within a week, and credit in the release notes if you want it.

## What counts

- A way past a sign-in: the site's, the admin pages', or the download's.
- Reading or changing another player's data, or a server's files, from the network.
- An archive that, when imported, reads or overwrites files outside the import's folders.
- Secrets (passwords, keys, tokens) in logs, pages or error messages.

The game's own protocol has no authentication (the client sends a player id), so a request that pretends to be another
player on the game's endpoints is known and not a vulnerability of OpenDMTQ. [docs/architecture.md](../docs/architecture.md)
explains what the server does against forged scores.

## Supported versions

Fixes go into `main` and the next release. A server stays safe on the latest one: with Docker Compose, `git pull`
then `./opendmtq up`; on a host install, the one command again (in a clone, `git pull` then `./opendmtq restart`); on
Windows, the newest bundle.
