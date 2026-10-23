#!/usr/bin/env python3
"""Image Context Guard: read images independently or inspect saved histories."""
import argparse
from pathlib import Path
import runpy
import sys


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or newer is required.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['read', 'history'])
    parser.add_argument('--version', action='version', version='Image Context Guard 0.1.0 (experimental)')
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', '--version'):
        parser.parse_args()
        return
    command = sys.argv[1]
    if command not in ('read', 'history'):
        parser.error('command must be read or history')
    filename = 'read_image.py' if command == 'read' else 'prune_history.py'
    script = Path(__file__).resolve().parent / 'skills' / 'image-context-guard' / 'scripts' / filename
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
