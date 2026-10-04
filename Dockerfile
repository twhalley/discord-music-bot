# syntax=docker/dockerfile:1
#
# Multi-stage build: a builder installs deps into a venv, the final image copies
# only that venv plus ffmpeg. Base image is pinned by digest for reproducibility
# and to defeat tag-mutation supply-chain attacks. Update the digest via
# Dependabot (see .github/dependabot.yml).

########################  builder  ########################
# The tag is load-bearing, not decoration: `FROM python@sha256:...` alone gives
# Dependabot no lineage to follow, so it resolves the newest `python` image and
# silently proposes major jumps (it moved us to Debian 13 / Python 3.14 once).
# Keeping the tag anchors updates to 3.13-slim-bookworm; the digest still pins
# the exact build.
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Create an isolated venv we can copy wholesale into the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install deps first (better layer caching), then the package itself.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# The venv is copied wholesale into the runtime image, and pip's _vendor tree
# (urllib3, msgpack, setuptools, ...) trails upstream fixes, so a runtime pip
# is a standing CVE feed the bot never uses. Strip it here, not there, so the
# runtime stage never contains it at all.
RUN pip uninstall -y pip

########################  runtime  ########################
# Keep this identical to the builder base — see the note above on the tag.
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS runtime

# ffmpeg is required to transcode/stream audio; libopus for Discord voice.
# The upgrade matters because the base is pinned by digest: security fixes that
# land in Debian after that digest was cut (e.g. libpcre2) only arrive here.
# The pip uninstall mirrors the builder stage -- the base image ships its own
# copy in the system site-packages, and nothing installs packages at runtime.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    # ensurepip carries a bundled pip wheel -- the same vendored-CVE payload
    # in zip form, and scanners unpack it. Nothing reinstalls pip here.
    && rm -rf /usr/local/lib/python3.13/ensurepip

# Run as an unprivileged, no-login user.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 botuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER botuser
WORKDIR /home/botuser

# No secrets baked in; the token arrives via the environment at runtime.
ENTRYPOINT ["python", "-m", "musicbot"]
