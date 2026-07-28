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

Behaviour worth knowing:

- **Links are restricted to YouTube and SoundCloud.** Anything else is refused —
  `/play` accepts free-form input from any member, and yt-dlp will fetch
  whatever it is handed, so the host is checked first. Plain text is searched,
  never fetched. See [`SECURITY.md`](SECURITY.md).
- **Commands are rate-limited per user**, the queue is capped at 100 tracks, and
  tracks longer than four hours are refused. Live streams (no duration) play.
- **The bot leaves when it has nothing to do** — shortly after the queue drains,
  or as soon as the last human leaves the channel — rather than holding a voice
  connection indefinitely. Queueing another track during the short grace period
  cancels the departure.
- **Some YouTube videos will refuse to play.** YouTube gates certain videos
  behind a sign-in when the request comes from a datacenter IP, so a link that
  works in your browser can fail on the server. The bot says so and suggests
  searching by name, which usually finds a playable upload. An optional
  [PO token provider](deploy/README.md#po-token-provider-optional) fixes most of
  these; genuinely age-restricted videos need an account and stay unplayable.

## Architecture

```
src/musicbot/
  __main__.py      entrypoint: load + validate config, run the bot
  config.py        fail-fast environment config
  bot.py           least-privilege intents, cog loading, command sync
  cogs/music.py    slash commands + voice client + player loop
  audio/queue.py   pure per-guild queue        (unit tested)
  audio/source.py  yt-dlp extraction (streamed) (unit tested, mocked)
  util/urls.py     URL helpers + host allowlist  (unit tested)
```

Tests live in `tests/`, including `test_voice_deps.py`, which asserts the voice
backends are installed — that failure is otherwise invisible until someone runs
a command in a live voice channel.

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

> **Voice needs two packages, not one.** discord.py 2.7 moved voice onto
> Discord's DAVE protocol, so `davey` is required alongside `PyNaCl`. Both are
> pinned in `pyproject.toml`. Without `davey` the bot starts, logs in and syncs
> commands looking perfectly healthy, then every `/play` fails inside
> `channel.connect()` with `RuntimeError: davey library needed in order to use
> voice`. `tests/test_voice_deps.py` guards this.

### Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | Bot token. The process refuses to start without it. |
| `LOG_LEVEL` | no | `DEBUG` / `INFO` (default) / `WARNING` / `ERROR`. |
| `DEV_GUILD_ID` | no | Sync commands to one guild instantly. Global sync takes up to an hour, so set this while developing. |
| `ALLOWED_GUILD_IDS` | no | Comma-separated guild ids the bot may serve. Empty means any. Set it and the bot leaves anywhere else, on join *and* at startup — useful if an invite link might leak. |

### Discord setup

1. Create an application + bot at the
   [Developer Portal](https://discord.com/developers/applications).
2. Copy the **bot token** into `.env` (`DISCORD_BOT_TOKEN`).
3. Invite it with scopes `bot` + `applications.commands` and permissions
   **Connect** + **Speak** (`3145728`) — nothing more:

   ```
   https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot+applications.commands&permissions=3145728
   ```

No **privileged intents** are needed, and none should be enabled in the portal:
`build_intents()` requests only `guilds` and `voice_states`.

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
podman run --rm --read-only \
  --tmpfs /tmp:rw,size=64m,mode=1777,noexec,nosuid,nodev \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --pids-limit=256 --memory=512m \
  -e DISCORD_BOT_TOKEN=... musicbot
```

These are the same flags [`deploy/musicbot.service`](deploy/musicbot.service)
runs in production, so a local container behaves like the deployed one.

## Deploy (free hosting)

Runs on an **Oracle Cloud Always Free** Ampere VM under `systemd` + `podman`,
rootless, as a dedicated service account with no `sudo` rights. See
[`deploy/README.md`](deploy/README.md) for the full walkthrough — including the
five GitHub Environment secrets, the OCI networking traps that make an instance
unreachable, host hardening, and where the logs live.

The published image is multi-arch, so an x86 shape works too; Ampere is
recommended because that is where the Always Free allowance sits.

## CI/CD & security

- **CI** — ruff, mypy, pytest+coverage, `pip-audit` on every PR; jobs are
  time-bounded and check out without persisting the job token.
- **Image** — Trivy gates **both** published architectures (amd64 *and* arm64)
  before pushing to GHCR, with SBOM + provenance. Scanning only the build
  architecture would leave the image the VM actually runs unexamined.
- **CodeQL** — code scanning on push/PR and weekly.
- **Dependabot** — pip, GitHub Actions, and the Docker base image. The base is
  pinned as `python:3.13-slim-bookworm@sha256:...`; the **tag is deliberate**,
  because a bare `FROM python@sha256:` gives Dependabot no lineage and it will
  propose jumps across Debian and Python major versions as if they were digest
  bumps.
- **Deploy** — manual, `production`-environment-gated SSH deploy with the VM's
  host key pinned, so the bot token is never handed to an impostor host.

[`SECURITY.md`](SECURITY.md) documents the full posture and, just as
importantly, a **Known limitations** section covering what is deliberately not
addressed.

Streaming from YouTube may conflict with its Terms of Service; this project is
intended for small, personal use.

## License

MIT — see [`LICENSE`](LICENSE).
