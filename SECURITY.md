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
- **Optional VPN egress is scoped, not global.** YouTube blocks datacenter
  addresses, so the bot's YouTube traffic can be routed through a WireGuard
  tunnel. Only the service account's uid is routed, and only to Google's
  published prefixes — the tunnel's routing table holds no default route, so
  everything else (Discord voice included) falls through to the host's normal
  path. A stock `wg-quick` config would seize the default route and break
  inbound SSH, locking out both administration and the deploy workflow.
- **Authenticated deploys.** The deploy SSH connection pins the VM's host key
  fingerprint, so the token is never handed to an impostor host.
- **No arbitrary outbound fetches.** `/play` takes free-form input from any
  guild member, so URLs are checked against a host allowlist (YouTube and
  SoundCloud) before reaching yt-dlp. Without it the bot is an SSRF primitive
  able to reach internal addresses such as a cloud metadata service. Non-URL
  input becomes a search term and is never fetched.
- **Untrusted values are validated, not trusted.** The stream URL yt-dlp returns
  becomes an `ffmpeg` argument, so it is checked to be `http(s)` — a value
  starting with `-` would be read as an option, and `file://` or `concat:`
  would make ffmpeg read something local. Track titles are markdown-escaped for
  display, mentions are disabled client-side, and titles are flattened before
  logging so newlines cannot forge log records.
- **Bounded per-guild resources.** Queues are capped, concurrent extractions are
  limited, per-user command cooldowns apply, yt-dlp has a socket timeout so a
  stalled host cannot hold a worker thread, and absurdly long tracks are
  refused. The bot disconnects once the last human leaves the channel rather
  than holding a voice connection and ffmpeg process indefinitely.
- **Optional guild allowlist.** `ALLOWED_GUILD_IDS` bounds the blast radius if
  an invite link leaks: the bot leaves any guild not on the list, both on join
  and on startup.
- **Hardened host access.** SSH is key-only and restricted to the two accounts
  that need it, with root login disabled, forwarding of every kind refused, and
  reduced auth attempts and grace time. The journal is size-capped so logging
  cannot fill the boot volume, and unattended security upgrades are enabled.
- **Every published architecture is scanned.** Trivy gates `amd64` *and*
  `arm64`; the image the deployment target actually runs is not exempt.
- **Pinned supply chain.** The base image is pinned by digest, all GitHub
  Actions are pinned by commit SHA, and Python dependencies are version-pinned.
- **Automated scanning.** Every change runs CodeQL, `pip-audit`, and a Trivy
  image scan (failing on HIGH/CRITICAL). Dependabot keeps everything current.
- **Deliberate deploys.** Deployment is a manual, environment-gated workflow
  that can require reviewer approval. CI jobs check out without persisting the
  job token, carry timeouts, and the deploy discards its registry credential
  and prunes superseded images once the service is up.

## Known limitations

Stated plainly rather than left implied:

- **The admin account is root-capable.** Ubuntu cloud images grant the default
  login account passwordless `sudo`. That account is for administration; the
  deploy key deliberately lives elsewhere. Anyone holding the *admin* key holds
  the machine.
- **`:latest` is a mutable tag.** The deploy workflow accepts an explicit tag,
  and `type=sha` tags are published, so pin one for a reproducible deploy.
- **Scanned and pushed images are separate builds.** They share a context and
  cache so they are the same in practice, but the pushed digest is not verified
  against the scanned one. Attestations are published (`provenance`, `sbom`)
  but not checked at deploy time.
- **Redirects are handled at the network layer, not the application one.** The
  host allowlist cannot see past an open redirect on an allowed host; the
  firewall rule is what actually contains that.
- **A VPN moves trust, it does not remove it.** With the tunnel enabled, the
  provider sees the bot's YouTube traffic instead of the cloud provider seeing
  it. The WireGuard private key is a credential on the host, held root-only at
  `0600`. It is off by default.
- **Optional YouTube cookies are an account credential**, off by default and
  documented with the trade-off stated plainly — a session cookie grants account
  access and bypasses 2FA. They were tested here and made playback *worse*, so
  the documentation recommends against them.

## A note on usage

Streaming audio from YouTube may conflict with YouTube's Terms of Service. This
project is intended for small, personal use. Respect the terms of any service
you stream from.
