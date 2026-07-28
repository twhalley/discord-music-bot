# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **Security → Report a
vulnerability** (private advisories), not in public issues. You'll get an
acknowledgement within a few days.

## Security posture

This project is built to be safe to run unattended:

- **Least-privilege bot.** Music playback uses only the `guilds` and
  `voice_states` gateway intents — no message-content intent, no broad OAuth
  scopes.
- **Secrets never touch the repo or image.** The bot token is injected at
  runtime via an environment file that is `0600` and owned by the unprivileged
  deploy user on the host, and stored in a protected GitHub Environment. `.env`
  is git-ignored.
- **Hardened container.** Read-only root filesystem, `--cap-drop=ALL`,
  `--security-opt=no-new-privileges`, non-root user, memory and PID limits.
- **Rootless on the host, under a dedicated account.** The container runs as a
  systemd *user* unit owned by a `musicbot` service account that holds the
  deploy key, is in no `sudo` group and has its password locked. Nothing in the
  deploy path invokes `sudo`. This matters because Ubuntu cloud images grant the
  *default* login account passwordless `sudo` — keeping the deploy key off that
  account is what stops it being a root credential. Administration stays on the
  separate default account.
- **Network egress is restricted.** yt-dlp follows redirects, so an open
  redirect on an allowed host could otherwise bounce a request onto the VPC or
  the instance metadata service. Host firewall rules deny the bot's uid
  everything link-local and RFC1918, excepting DNS — which shares an address
  with the metadata service on Oracle Cloud. The application allowlist and this
  rule are independent layers; neither is relied on alone.
- **Authenticated deploys.** The deploy SSH connection pins the VM's host key
  fingerprint, so the token is never handed to an impostor host.
- **No arbitrary outbound fetches.** `/play` takes free-form input from any
  guild member, so URLs are checked against a host allowlist (YouTube and
  SoundCloud) before reaching yt-dlp. Without it the bot is an SSRF primitive
  able to reach internal addresses such as a cloud metadata service. Non-URL
  input becomes a search term and is never fetched.
- **Bounded per-guild resources.** Queues are capped and concurrent extractions
  are limited, so a member cannot grow memory or exhaust the worker pool by
  spamming commands.
- **Every published architecture is scanned.** Trivy gates `amd64` *and*
  `arm64`; the image the deployment target actually runs is not exempt.
- **Pinned supply chain.** The base image is pinned by digest, all GitHub
  Actions are pinned by commit SHA, and Python dependencies are version-pinned.
- **Automated scanning.** Every change runs CodeQL, `pip-audit`, and a Trivy
  image scan (failing on HIGH/CRITICAL). Dependabot keeps everything current.
- **Deliberate deploys.** Deployment is a manual, environment-gated workflow
  that can require reviewer approval.

## A note on usage

Streaming audio from YouTube may conflict with YouTube's Terms of Service. This
project is intended for small, personal use. Respect the terms of any service
you stream from.
