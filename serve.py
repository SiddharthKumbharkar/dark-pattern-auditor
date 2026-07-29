#!/usr/bin/env python3
"""CLI: run server.py's FastAPI dashboard backend via uvicorn.

Usage:
    python3 serve.py
    python3 serve.py --host 0.0.0.0 --port 8080 --reload
"""

import argparse
import sys

import uvicorn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the FastAPI dashboard backend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on source changes (development only)")
    args = parser.parse_args(argv)

    # Always pass the import-string form ("server:app") rather than the
    # app object directly -- uvicorn requires that for --reload to work,
    # and it works identically without --reload, so there's no need for
    # two code paths.
    uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
