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
- **Rootless on the host.** The container runs under a systemd *user* unit as an
  unprivileged account with no `sudo` rights, so a compromised deploy key does
  not confer root on the VM.
- **Authenticated deploys.** The deploy SSH connection pins the VM's host key
  fingerprint, so the token is never handed to an impostor host.
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
