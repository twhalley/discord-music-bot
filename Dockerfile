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
FROM python:3.13-slim-bookworm@sha256:fcbd8dfc2605ba7c2eca646846c5e892b2931e41f6227985154a596f26ab8ed7 AS builder

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

########################  runtime  ########################
# Keep this identical to the builder base — see the note above on the tag.
FROM python:3.13-slim-bookworm@sha256:fcbd8dfc2605ba7c2eca646846c5e892b2931e41f6227985154a596f26ab8ed7 AS runtime

# ffmpeg is required to transcode/stream audio; libopus for Discord voice.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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
