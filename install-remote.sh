#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  ⚡ OptimusPrime — installing..."
echo ""

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python 3.8+ required."
    echo "    Install from: https://python.org/downloads"
    exit 1
fi

PYVER=$(python3 -c 'import sys; print(sys.version_info.major*10+sys.version_info.minor)')
if [[ "$PYVER" -lt 38 ]]; then
    echo "  ✗ Python 3.8+ required. Found: $(python3 --version)"
    exit 1
fi

# 2. Download OptimusPrime
INSTALL_DIR="$HOME/.optimusprime"
mkdir -p "$INSTALL_DIR"

if command -v git &>/dev/null; then
    if [[ -d "$INSTALL_DIR/repo/.git" ]]; then
        echo "  ↻ Updating OptimusPrime..."
        git -C "$INSTALL_DIR/repo" pull --quiet
    else
        echo "  ↓ Downloading OptimusPrime..."
        git clone --quiet \
            https://github.com/aarshsharma2803-stack/optimusprime.git \
            "$INSTALL_DIR/repo"
    fi
else
    # No git — download zip
    echo "  ↓ Downloading OptimusPrime (zip)..."
    curl -fsSL \
        https://github.com/aarshsharma2803-stack/optimusprime/archive/refs/heads/main.zip \
        -o /tmp/optimusprime.zip
    unzip -q /tmp/optimusprime.zip -d /tmp/
    rm -rf "$INSTALL_DIR/repo"
    mv /tmp/optimusprime-main "$INSTALL_DIR/repo"
    rm /tmp/optimusprime.zip
fi

# 3. Run the real installer from the downloaded repo
bash "$INSTALL_DIR/repo/install.sh"
