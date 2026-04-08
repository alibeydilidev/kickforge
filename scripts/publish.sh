#!/usr/bin/env bash
# KickForge publish script
# Usage:
#   ./scripts/publish.sh build        — build sdist + wheel
#   ./scripts/publish.sh test-publish — upload to TestPyPI
#   ./scripts/publish.sh publish      — upload to PyPI
#   ./scripts/publish.sh clean        — remove build artifacts

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd_build() {
    echo "==> Cleaning old builds..."
    rm -rf dist/ build/ *.egg-info
    echo "==> Building sdist + wheel..."
    python -m build
    echo ""
    echo "==> Build artifacts:"
    ls -lh dist/
    echo ""
    echo "==> Validating with twine..."
    python -m twine check dist/*
}

cmd_test_publish() {
    if [ ! -d dist ]; then
        echo "No dist/ found. Run './scripts/publish.sh build' first."
        exit 1
    fi
    echo "==> Uploading to TestPyPI..."
    python -m twine upload --repository testpypi dist/*
    echo ""
    echo "==> Done! Install with:"
    echo "    pip install --index-url https://test.pypi.org/simple/ kickforge"
}

cmd_publish() {
    if [ ! -d dist ]; then
        echo "No dist/ found. Run './scripts/publish.sh build' first."
        exit 1
    fi
    echo "==> Uploading to PyPI..."
    python -m twine upload dist/*
    echo ""
    echo "==> Done! Install with:"
    echo "    pip install kickforge"
}

cmd_clean() {
    echo "==> Cleaning build artifacts..."
    rm -rf dist/ build/ *.egg-info
    echo "Done."
}

case "${1:-help}" in
    build)        cmd_build ;;
    test-publish) cmd_test_publish ;;
    publish)      cmd_publish ;;
    clean)        cmd_clean ;;
    *)
        echo "Usage: $0 {build|test-publish|publish|clean}"
        exit 1
        ;;
esac
