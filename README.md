# discord-music-bot

A hardened, self-hostable Discord bot that streams **YouTube** and **SoundCloud**
audio into voice channels via slash commands — with a full, secure DevOps
pipeline (CI, container scanning, GHCR publishing, and gated deploys).

> Structured so the [embed-fixer](https://github.com/twhalley/embed-fixer)
> URL-rewriting feature can drop in later as a cog — the rewrite table already
> lives in [`util/urls.py`](src/musicbot/util/urls.py) and is unit tested.

## Commands

| Command | Description |
| --- | --- |
| `/play <url-or-search>` | Play or queue a YouTube/SoundCloud link, or search text |
| `/skip` | Skip the current track |
| `/pause` · `/resume` | Pause / resume playback |
| `/queue` | Show the upcoming tracks |
| `/nowplaying` | Show the current track |
| `/stop` | Stop, clear the queue, and leave the channel |

## Architecture

```
src/musicbot/
  __main__.py      entrypoint: load + validate config, run the bot
  config.py        fail-fast environment config
  bot.py           least-privilege intents, cog loading, command sync
  cogs/music.py    slash commands + voice client + player loop
  audio/queue.py   pure per-guild queue        (unit tested)
  audio/source.py  yt-dlp extraction (streamed) (unit tested, mocked)
  util/urls.py     URL helpers + embed-fix table (unit tested)
```

The Discord-facing layer is thin; all logic worth testing (queueing, query
resolution, config, URL rewriting) is pure and covered by `pytest`.

## Run locally

Requires Python 3.11+ and `ffmpeg` on your PATH.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then paste your DISCORD_BOT_TOKEN
python -m musicbot
```

### Discord setup

1. Create an application + bot at the
   [Developer Portal](https://discord.com/developers/applications).
2. Copy the **bot token** into `.env` (`DISCORD_BOT_TOKEN`).
3. Invite the bot with the `applications.commands` scope and the **Connect** +
   **Speak** voice permissions. (No privileged intents are needed for music.)

## Develop

```bash
ruff check . && ruff format --check .   # lint + format
mypy                                    # types
pytest                                  # tests + 80% coverage gate
```

## Container

Multi-stage, non-root, digest-pinned base. Built and scanned in CI, published to
`ghcr.io/<owner>/discord-music-bot`.

```bash
podman build -t musicbot .
podman run --rm --read-only --tmpfs /tmp --cap-drop=ALL \
  --security-opt=no-new-privileges -e DISCORD_BOT_TOKEN=... musicbot
```

## Deploy (free hosting)

Runs on an **Oracle Cloud Always Free** ARM VM under `systemd` + `podman`. See
[`deploy/README.md`](deploy/README.md) for the full walkthrough and the
GitHub Environment secrets to set.

## CI/CD & security

- **CI** — ruff, mypy, pytest+coverage, `pip-audit` on every PR.
- **Image** — Trivy scan (fails on HIGH/CRITICAL) before a multi-arch
  (amd64+arm64) push to GHCR, with SBOM + provenance.
- **CodeQL** — code scanning on push/PR and weekly.
- **Dependabot** — pip, GitHub Actions, and Docker base image.
- **Deploy** — manual, `production`-environment-gated SSH deploy.

See [`SECURITY.md`](SECURITY.md) for the full posture and a note on YouTube's ToS.

## License

MIT — see [`LICENSE`](LICENSE).
