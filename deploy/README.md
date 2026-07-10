# Deploying to an Oracle Cloud "Always Free" VM

This bot runs as a hardened `podman` container managed by `systemd`. GitHub
Actions builds and scans the image, pushes it to GHCR, and a manual **Deploy**
workflow SSHes into the VM to pull the new image and restart the service.

## 1. Create the free VM

1. Sign up at <https://cloud.oracle.com> (Always Free tier; a card is required
   for identity but is not charged).
2. Create a **VM.Standard.A1.Flex** (Ampere ARM) instance — 1 OCPU / 6 GB is
   plenty. Use an **Ubuntu 22.04/24.04** image. ARM matches the `arm64` image
   the pipeline builds.
3. Save the SSH private key Oracle generates — it becomes the `SSH_PRIVATE_KEY`
   secret below.
4. No inbound ports are needed (the bot only makes **outbound** connections to
   Discord), so you can leave the default security list closed.

## 2. Prepare the VM (one time)

```bash
sudo apt-get update && sudo apt-get install -y podman
# Let the deploy user run the few commands the workflow needs without a password:
echo "$USER ALL=(root) NOPASSWD: /usr/bin/podman, /usr/bin/tee, /usr/bin/chmod, /usr/bin/systemctl" \
  | sudo tee /etc/sudoers.d/musicbot
sudo install -m 644 /dev/stdin /etc/systemd/system/musicbot.service < musicbot.service  # or scp it up
sudo systemctl daemon-reload
sudo systemctl enable musicbot.service   # starts on boot; first real start happens on deploy
```

> The deploy workflow writes `/etc/musicbot.env` (the token) and
> `/etc/musicbot.image` (the image tag) as root-owned `0600` files, so they are
> never committed and never appear in the image.

## 3. Add GitHub secrets

Repo **Settings -> Environments -> New environment -> `production`**, then add:

| Secret | Value |
| --- | --- |
| `SSH_HOST` | VM public IP |
| `SSH_USER` | e.g. `ubuntu` |
| `SSH_PRIVATE_KEY` | the private key from step 1 |
| `DISCORD_BOT_TOKEN` | the bot token from the Discord Developer Portal |

Optionally set **Required reviewers** on the environment so every deploy needs a
click to approve.

## 4. Deploy

Push to `main` → the **Build & publish image** workflow builds, scans (Trivy),
and pushes `ghcr.io/OWNER/REPO:latest`. Then run the **Deploy** workflow
(Actions tab → Deploy → *Run workflow*), optionally passing a specific tag.

## Updating

Dependabot opens PRs for Python deps, Actions, and the base image. Merge →
image rebuilds → run Deploy. To roll back, run Deploy with an older `type=sha`
tag (visible on the GHCR package page).
