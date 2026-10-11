#!/usr/bin/env bash
set -euo pipefail

uv run main.py --ui-condition c3 --highlight_mouse --log \
	--grounding text \
	--stealth \
	--locale ko-KR \
	--timezone Asia/Seoul \
	--user-agent "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
