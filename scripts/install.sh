#!/usr/bin/env bash
set -euo pipefail

# Forge one-command bootstrap installer (Linux / macOS).
#
# Detects platform, downloads the matching release archive and checksum,
# verifies SHA-256, extracts, and delegates durable installation to the
# verified native executable.
#
# Supports pinning a version via FORGE_VERSION.
#
# Usage:
#   curl -fsSL https://github.com/<owner>/forge/releases/latest/download/install.sh | bash
#   FORGE_VERSION=0.1.0-alpha.1 bash install.sh

RELEASE_BASE="${FORGE_RELEASE_BASE:-https://github.com/anomalyco/forge/releases/download}"

detect_target() {
    local os arch
    case "$(uname -s)" in
        Linux)  os="linux" ;;
        Darwin) os="macos" ;;
        *)      echo "Unsupported OS: $(uname -s)" >&2; exit 1 ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64)   arch="x64" ;;
        aarch64|arm64)  arch="arm64" ;;
        *)              echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
    esac
    echo "${os}-${arch}"
}

VERSION="${FORGE_VERSION:-${FORGE_ALPHA_VERSION:-latest}}"
TARGET="$(detect_target)"
echo "Forge installer - ${VERSION} (${TARGET})"

if [ "$VERSION" = "latest" ]; then
    echo "Resolving latest version..."
    VERSION=$(curl -fsSL "${RELEASE_BASE}/latest.txt" 2>/dev/null || echo "")
    if [ -z "$VERSION" ]; then
        echo "error: unable to resolve latest version" >&2
        exit 1
    fi
fi

RELEASE_URL="${RELEASE_BASE}/${VERSION}"
ARCHIVE="forge-${VERSION}-${TARGET}.tar.gz"
CHECKSUM="forge-${VERSION}-${TARGET}.sha256"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading ${RELEASE_URL}/${ARCHIVE}..."
curl -fsSL -o "${TMPDIR}/${ARCHIVE}" "${RELEASE_URL}/${ARCHIVE}"

echo "Downloading checksum..."
curl -fsSL -o "${TMPDIR}/${CHECKSUM}" "${RELEASE_URL}/${CHECKSUM}"

echo "Verifying checksum..."
EXPECTED=$(cut -d' ' -f1 "${TMPDIR}/${CHECKSUM}")
ACTUAL=$(sha256sum "${TMPDIR}/${ARCHIVE}" | cut -d' ' -f1)
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "error: checksum mismatch" >&2
    echo "  expected: ${EXPECTED}" >&2
    echo "  actual:   ${ACTUAL}" >&2
    exit 1
fi
echo "Checksum verified."

echo "Extracting..."
tar xzf "${TMPDIR}/${ARCHIVE}" -C "${TMPDIR}"

EXTRACTED="$(find "${TMPDIR}" -maxdepth 1 -type d -name 'forge-*' | head -1)"
if [ ! -d "$EXTRACTED" ]; then
    echo "error: extraction did not produce expected directory" >&2
    exit 1
fi

EXE="${EXTRACTED}/bin/forge"
if [ ! -f "$EXE" ]; then
    echo "error: executable not found" >&2
    exit 1
fi
chmod +x "$EXE"

echo "Running installer..."
"$EXE" install --version "$VERSION" --release-base "${RELEASE_BASE}/${VERSION}"

echo "Forge ${VERSION} installation complete."
