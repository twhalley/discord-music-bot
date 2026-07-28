# Deploying to an Oracle Cloud "Always Free" VM

This bot runs as a hardened `podman` container managed by `systemd`. GitHub
Actions builds and scans the image, pushes it to GHCR, and a manual **Deploy**
workflow SSHes into the VM to pull the new image and restart the service.

The whole path is: **create the VM → make it reachable → prep it once → add five
GitHub secrets → run the Deploy workflow.** Follow the sections in order.

> **The one thing to get right:** the Deploy workflow SSHes *into* the VM, so the
> VM needs a **public IP** and **inbound TCP 22**. An instance can sit happily in
> the `Running` state with neither, and nothing in the console will tell you.
> Section 2 exists entirely because of this.

---

## 1. Create the free VM (Oracle Cloud console)

Sign up at <https://cloud.oracle.com> (Always Free tier; a card is required for
identity verification but is not charged). Then **Menu → Compute → Instances →
Create instance** and work through the wizard:

### Basic information
- **Name:** anything, e.g. `discord-music-bot`.
- **Image:** click *Edit* → **Ubuntu** (22.04 or 24.04). The default is often
  Oracle Linux — change it to Ubuntu.
- **Shape:** click *Change shape* → **Ampere** tab → **VM.Standard.A1.Flex**,
  then set **1 OCPU / 6 GB**.
  - **Ampere (ARM) is recommended, not required.** The pipeline publishes a
    **multi-arch** image (`linux/amd64,linux/arm64` — see
    `.github/workflows/docker.yml`), so an x86 shape will run the container
    fine. Choose Ampere because that's where the Always Free allowance is:
    **3,000 OCPU-hours and 18,000 GB-hours per month**, which covers 1 OCPU /
    6 GB running continuously with room to spare.

### Networking
- **Primary network:** *Create new virtual cloud network* (lets the wizard build
  a VCN + public subnet for you). Leave the generated names as-is.
- **Subnet:** *Create new public subnet*. Leave CIDR `10.0.0.0/24`.
  - ⚠️ It **must** be a public subnet. A subnet's *"prohibit public IP
    addresses"* flag is **immutable after creation** — a private subnet can
    never be converted, and no VNIC in it can ever hold a public IP.
- **Assign a public IPv4 address:** turn this **ON**.
  - ⚠️ **If this toggle is greyed out:** open **Private IPv4 address assignment
    → Subnet IPv4 prefixes** and select the `10.0.0.0/24` prefix. The toggle
    becomes clickable immediately. The console shows **no error text** explaining
    this, and it is the single most likely reason an instance comes up with no
    public IP.
- Ignore the **IPv6** section (leave it off).

### Add SSH keys

Generate the key yourself first, then paste the public half — don't let Oracle
generate one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oracle-admin -N "" -C "admin@discord-music-bot"
```

- Choose **Paste public keys** and paste the contents of `~/.ssh/oracle-admin.pub`.
- The private half never leaves your machine, and it can't be lost to a browser
  download you forget to save.

> ⚠️ Oracle's **Save private key** download is offered **once** and cannot be
> repeated. If you lose it there is no way back in: instance metadata is read
> only at first boot, so a new key cannot be authorised without existing access,
> and the recovery paths (serial console into GRUB, or detaching the boot volume
> onto a second instance) are far more work than recreating the VM.

This is the **admin** key. The deploy key is a separate, unprivileged one
created in section 3.

### Finish
Click **Create** and wait for the instance state to go **Running**. Then check
the **Public IPv4 address** field on the instance details page:

- **It shows an address** → note it down (it's your `SSH_HOST`) and go to
  section 3.
- **It's blank or says "-"** → go to section 2. The instance is fine; it just
  isn't reachable yet.

The default login user on Ubuntu images is **`ubuntu`**. Use it for the setup in
section 3 — but note it is *not* your `SSH_USER` secret, which is the dedicated
`musicbot` service account created there.

---

## 2. Networking: making the instance reachable

A reachable OCI instance is **four separate objects**, not one setting. The
create wizard usually assembles all four for you, but when it doesn't, it fails
silently — you get a `Running` instance you cannot reach. Check them in order;
each one is independently capable of breaking connectivity.

| # | Object | Where to check |
| --- | --- | --- |
| 1 | A **public subnet** | VCN → Subnets → your subnet → *Subnet access* |
| 2 | An **internet gateway** on the VCN | VCN → Internet Gateways |
| 3 | A **route rule** `0.0.0.0/0` → that gateway | VCN → Route Tables |
| 4 | A **public IP** mapped to the VNIC's primary private IP | Instance → Networking → Attached VNICs |

### 1. Public subnet

VCN → **Subnets** → your subnet → **Subnet access**. It reads either *Public
Subnet* or *Private Subnet*.

If it says **Private Subnet**, stop — you cannot fix this in place. The
"prohibit public IP addresses" flag is set at creation and cannot be changed.
Your options:

- **Terminate and recreate the instance** in a public subnet (cleanest, and
  cheap while the VM is still empty). Untick *Preserve boot volume* so you don't
  leave an orphaned volume behind.
- Attaching a *secondary* VNIC in a public subnet technically works, but needs
  source-based routing configured inside Ubuntu for SSH to reply on the right
  interface. Not worth it for a fresh VM.

### 2. Internet gateway

VCN page → **Internet Gateways**. If the list is empty, **Create Internet
Gateway** (defaults are fine).

### 3. Route rule — check the table the VNIC *actually* uses

VCN → **Route Tables**. You need a rule with destination `0.0.0.0/0` and target
type **Internet Gateway** pointing at the gateway from step 2.

⚠️ **A VCN can have several route tables, and the quick action sometimes writes
the rule into a different one than your VNIC points at.** Don't just confirm
"a route table has the rule" — confirm *the right one* does:

1. Instance → **Networking** → **Attached VNICs** → primary VNIC → note its
   **Route table**.
2. Open **that** route table and verify the `0.0.0.0/0` rule is in it.

### 4. Public IP on the VNIC

This is the step people miss: objects 1–3 make the subnet routable but don't
hand out an address. See the recovery path below.

### Recovery: adding a public IP to an already-running instance

1. Instance → **Networking** → **Attached VNICs** → click the **primary VNIC**.
2. Open the **IP administration** tab.
   - The console layout varies by tenancy and region — in some it's a tab, in
     others a *Resources* sidebar entry called *IPv4 Addresses*. Same thing.
3. Click the **three-dot menu** on the **primary private IP** row → **Edit**.
4. **Public IP type → Ephemeral public IP**.
5. Leave **Route Table** on *"Use VCN, subnet or VNIC route table"*.
6. **Update**, then refresh the instance page — **Public IPv4 address** is now
   populated.

**Ephemeral vs reserved.** Both are free, and Always Free tenancies include one
reserved public IP.

- **Ephemeral** survives stop/start and reboots; it is released only when the
  instance is **terminated**.
- **Reserved** survives termination too. Use it if you'd rather not update the
  `SSH_HOST` secret after rebuilding the VM.

### ⚠️ Don't run "Connect public subnet to internet" twice

The **Connect public subnet to internet** quick action creates the internet
gateway, the route rule, and a network security group in one click — but it is
**not usefully idempotent**. Each run attaches *another* NSG to the VNIC. Running
it three times leaves three identically-named `ig-quick-action-NSG` entries on
one VNIC: harmless in effect, but the rule set becomes unreadable.

If you've already done it: once connectivity works, go to the VNIC → **Edit**
next to **Network security groups** and remove the duplicates, keeping the one
that actually carries the SSH rule.

### Ingress for TCP 22

Traffic is filtered by the **union** of the subnet's **security list** *and* any
**NSGs** attached to the VNIC — either one permitting the traffic is enough.
That also means checking only one of them can mislead you.

Verify at least one of these allows it:

- **Security list:** VCN → Security Lists → your subnet's list → **Ingress
  Rules** → source `0.0.0.0/0`, protocol **TCP**, destination port **22**.
- **NSG:** VNIC → Network security groups → open the attached NSG → same rule.

Don't assume the quick-action NSG has the SSH rule — open it and confirm.

> **On the bot itself:** it only makes *outbound* connections to Discord, so no
> application ports are ever needed. Port 22 is required for **setup and
> deployment**, not for the bot to run.

### Verify

```bash
chmod 600 /path/to/your-key.key
ssh -i /path/to/your-key.key ubuntu@<PUBLIC_IP>
```

- **Connection timed out** → networking: re-check objects 1–4 and the ingress
  rule above.
- **Connection refused** → networking is fine; sshd isn't up. Check the instance
  is `Running` and give it a minute after first boot.
- **Permission denied (publickey)** → networking is fine; wrong key or wrong
  user. The Ubuntu images use `ubuntu`, not `opc` (that's Oracle Linux).

---

## 3. Prepare the VM (one time)

The bot runs **rootless**, under a **dedicated `musicbot` service account** that
holds the deploy key and has no `sudo` rights at all. Nothing here needs root —
no privileged ports, no host mounts, and the image already drops to an
unprivileged user internally.

> **Why a separate account, rather than `ubuntu`?** Ubuntu cloud images ship
> `/etc/sudoers.d/90-cloud-init-users` granting the default login account
> `NOPASSWD:ALL`. Putting the deploy key on `ubuntu` therefore makes
> `SSH_PRIVATE_KEY` a *root* credential no matter how carefully the deploy
> script avoids `sudo`. A dedicated account is what actually makes the claim
> true. Keep using `ubuntu` for administration.

Generate the deploy key **on your machine** (so the private half never travels):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/musicbot-deploy -N "" -C "github-deploy"
```

Then SSH in as `ubuntu`, `scp` the unit up, and run:

```bash
sudo apt-get update && sudo apt-get install -y podman uidmap

# Dedicated service account: no sudo group, password locked, key auth only.
sudo useradd --create-home --shell /bin/bash musicbot
sudo passwd -l musicbot
MB_UID=$(id -u musicbot)

# Rootless podman needs subuid/subgid ranges.
grep -q '^musicbot:' /etc/subuid || \
  sudo usermod --add-subuids 200000-265535 --add-subgids 200000-265535 musicbot

# Install the deploy public key. Forwarding is disabled: this key exists to run
# one deploy script, not to tunnel into the VPC.
sudo install -d -m 700 -o musicbot -g musicbot /home/musicbot/.ssh
printf 'no-agent-forwarding,no-port-forwarding,no-X11-forwarding %s\n' \
  "$(cat musicbot-deploy.pub)" | sudo tee /home/musicbot/.ssh/authorized_keys >/dev/null
sudo chown musicbot:musicbot /home/musicbot/.ssh/authorized_keys
sudo chmod 600 /home/musicbot/.ssh/authorized_keys

# Let its services run without a login session — i.e. start at boot.
sudo loginctl enable-linger musicbot

sudo install -d -m 700 -o musicbot -g musicbot \
  /home/musicbot/.config/systemd/user /home/musicbot/.config/musicbot
sudo install -m 644 -o musicbot -g musicbot musicbot.service \
  /home/musicbot/.config/systemd/user/musicbot.service

sudo -u musicbot env XDG_RUNTIME_DIR=/run/user/$MB_UID \
  systemctl --user daemon-reload
sudo -u musicbot env XDG_RUNTIME_DIR=/run/user/$MB_UID \
  systemctl --user enable musicbot.service  # first real start happens on deploy
```

Confirm the account really is unprivileged, and that the cgroup controllers the
unit's `--memory` and `--pids-limit` flags depend on are delegated to it:

```bash
ssh -i ~/.ssh/musicbot-deploy musicbot@<PUBLIC_IP> 'id; sudo -n true'
cat /sys/fs/cgroup/user.slice/user-$(id -u musicbot).slice/cgroup.controllers
```

`sudo -n true` must fail. `memory` and `pids` must both appear — if they're
missing the container fails to start with a cgroup error rather than quietly
ignoring the limits.

### Egress restrictions (recommended)

yt-dlp follows redirects, so an open redirect on an allowed host could bounce a
request onto the VPC or the instance metadata service — the application's host
allowlist can't see past a redirect. Denying it at the network layer closes that:

```bash
sudo nft -f - <<EOF
table inet musicbot
delete table inet musicbot
table inet musicbot {
    chain output {
        type filter hook output priority -10; policy accept;
        # DNS FIRST: on Oracle Cloud the resolver shares an address with the
        # metadata service, so a blanket block breaks name resolution entirely.
        ip daddr 169.254.169.254 udp dport 53 accept
        ip daddr 169.254.169.254 tcp dport 53 accept
        skuid $(id -u musicbot) ip daddr 169.254.0.0/16 drop
        skuid $(id -u musicbot) ip daddr 10.0.0.0/8 drop
        skuid $(id -u musicbot) ip daddr 172.16.0.0/12 drop
        skuid $(id -u musicbot) ip daddr 192.168.0.0/16 drop
    }
}
EOF
```

Scoped to the service account's uid, so root and the admin account are
unaffected — `apt`, cloud-init and `systemd-resolved` all legitimately use these
ranges. Its own table at priority `-10` leaves Oracle's default ruleset alone;
remove it with `sudo nft delete table inet musicbot`.

Persist it across reboots with a oneshot unit (`ExecStart=/usr/sbin/nft -f
/etc/nftables-musicbot.conf`) rather than `/etc/nftables.conf`, whose default
begins with `flush ruleset` and would drop Oracle's rules — including the one
permitting inbound SSH.

### Host hardening (recommended)

**SSH.** A drop-in leaves the vendor config untouched and reverts by deleting
one file. On Ubuntu, `sshd_config` includes `sshd_config.d/*.conf` at the top
and *first value wins*, so check for an existing lower-numbered drop-in
(`60-cloudimg-settings.conf`) before assuming yours takes effect:

```bash
sudo tee /etc/ssh/sshd_config.d/99-musicbot-hardening.conf >/dev/null <<'EOF'
AllowUsers ubuntu musicbot
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
LoginGraceTime 30
AllowTcpForwarding no
X11Forwarding no
AllowAgentForwarding no
PermitTunnel no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
sudo sshd -t && sudo systemctl reload ssh
```

⚠️ **Validate with `sshd -t` before reloading, and test a *new* connection
before closing your current one.** A reload does not drop existing sessions, so
an open shell is your way back from a mistake.

**Journal size.** The bot logs a line per track, so an unbounded journal is a
slow path to a full boot volume — which takes the bot down:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/99-musicbot.conf >/dev/null <<'EOF'
[Journal]
SystemMaxUse=500M
SystemKeepFree=2G
MaxRetentionSec=1month
EOF
sudo systemctl restart systemd-journald
```

**Security updates.** `unattended-upgrades` is enabled by default on Ubuntu
cloud images, but a freshly created VM can still carry a backlog it hasn't
processed yet. Apply it once at setup and reboot if asked:

```bash
sudo apt-get update && sudo apt-get -y upgrade
[ -f /var/run/reboot-required ] && sudo systemctl reboot
```

Finally, capture the host key fingerprint for the `SSH_HOST_FINGERPRINT` secret.
Run this **from your laptop**, not the VM:

```bash
ssh-keyscan -t ed25519 <PUBLIC_IP> 2>/dev/null | ssh-keygen -lf - | awk '{print $2}'
```

> The deploy workflow writes `~/.config/musicbot/env` (the token) and
> `~/.config/musicbot/image` (the image tag) as `0600` files owned by the deploy
> user, so they are never committed and never appear in the image. You do **not**
> create these by hand.
>
> **Upgrading from an older rootful setup?** Remove the leftovers:
> `sudo systemctl disable --now musicbot.service`, then
> `sudo rm -f /etc/systemd/system/musicbot.service /etc/sudoers.d/musicbot
> /etc/musicbot.env /etc/musicbot.image`.

---

## 4. Add GitHub secrets

The Deploy workflow runs in the `production` **environment**, so the secrets must
be added there (not as plain repository secrets, or the job won't see them).

Repo **Settings → Environments → New environment → name it `production`**, then
**Add environment secret** for each of these:

| Secret | How to get the value |
| --- | --- |
| `SSH_HOST` | The VM's **Public IPv4 address** from the instance details page. |
| `SSH_USER` | `musicbot` — the dedicated service account from section 3, **not** `ubuntu`. |
| `SSH_PRIVATE_KEY` | The **full contents** of `~/.ssh/musicbot-deploy` — including the `-----BEGIN...-----` and `-----END...-----` lines. |
| `SSH_HOST_FINGERPRINT` | The `ssh-keyscan` output from section 3, e.g. `SHA256:abc123…`. |
| `DISCORD_BOT_TOKEN` | Discord Developer Portal → your app → **Bot** → **Reset/Copy Token**. |

`GITHUB_TOKEN` is **auto-provided** by GitHub Actions — do not add it.
`DEV_GUILD_ID` and `LOG_LEVEL` are optional local-dev vars (see `.env.example`),
not secrets — ignore them for production.

Optionally set **Required reviewers** on the environment so every deploy needs a
click to approve.

> ⚠️ **`SSH_HOST_FINGERPRINT` is not optional.** Without it the SSH action
> accepts *any* host key, so anything answering on `SSH_HOST` — a recycled
> ephemeral IP, a hijacked route — receives your `DISCORD_BOT_TOKEN`. If you
> rebuild the VM, the host key changes and this secret must be regenerated
> alongside `SSH_HOST`.

> ⚠️ **Keep `SSH_HOST` current.** If the VM is terminated and rebuilt, an
> ephemeral public IP changes. A stale `SSH_HOST` fails at the **"Deploy over
> SSH"** step of the Deploy job with a connection timeout — the error names the
> SSH action, not the secret, so it reads like a broken workflow rather than a
> stale value. Check this first when a previously-working deploy starts timing
> out. A **reserved** public IP (section 2) avoids the problem.

---

## 5. Deploy

Push to `main` → the **Build & publish image** workflow builds, scans (Trivy),
and pushes `ghcr.io/OWNER/REPO:latest`. Then run the **Deploy** workflow
(Actions tab → Deploy → *Run workflow*), optionally passing a specific tag.

Verify it came up:

```bash
ssh -i ~/.ssh/musicbot-deploy musicbot@<PUBLIC_IP> \
  'systemctl --user --no-pager status musicbot.service'
```

---

## Updating

Dependabot opens PRs for Python deps, Actions, and the base image. Merge →
image rebuilds → run Deploy. To roll back, run Deploy with an older `type=sha`
tag (visible on the GHCR package page).
