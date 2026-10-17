#!/usr/bin/env bash
# install ox: the language and the `ox` command
set -euo pipefail

cd "$(dirname "$0")"

echo "▶ installing ox (requires python3.9+)"
python3 -m pip install . --quiet

echo ""
ox version
echo ""
echo "✓ done. try it:"
echo "    ox init my-tool && cd my-tool && ox run ."
echo "    ox run examples/hello.ox"
