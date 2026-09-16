#!/usr/bin/env python3
"""Check local document links, structured assets and offline reference boundaries.

SPDX-License-Identifier: MIT
This lightweight check is not a security audit or a hardware test.
"""
from pathlib import Path
import json
import re
import sys
from urllib.parse import unquote, urlsplit


def check(root: Path):
    """Return actionable repository consistency errors without changing files."""
    errors = []
    required = ['README.md', 'LICENSE', 'docs/STATUS.md', 'docs/VALIDATION.md',
                'reference/index.html', 'reference/core.js', 'schemas/session.schema.json',
                'schemas/proposal.schema.json', '.github/workflows/ci.yml']
    for name in required:
        if not (root / name).is_file():
            errors.append('Missing required file: ' + name)
    for path in sorted(root.rglob('*.md')):
        if any(part in {'.git', 'node_modules', '.venv', 'venv', 'build', 'dist', '__pycache__'}
               for part in path.relative_to(root).parts):
            continue
        text = path.read_text(encoding='utf-8')
        for link in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', text):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if root != target and root not in target.parents:
                errors.append(str(path.relative_to(root)) + ': link leaves repository')
            elif not target.exists():
                errors.append(str(path.relative_to(root)) + ': missing link ' + link)
    for path in sorted((root / 'schemas').glob('*.json')):
        try:
            schema = json.loads(path.read_text(encoding='utf-8'))
            if schema.get('type') != 'object' or schema.get('additionalProperties') is not False:
                errors.append(path.name + ': expected a closed object schema')
            if set(schema.get('required', [])) != set(schema.get('properties', {})):
                errors.append(path.name + ': inconsistent required fields')
        except (ValueError, OSError):
            errors.append(path.name + ': invalid JSON schema file')
    html = (root / 'reference/index.html').read_text(encoding='utf-8')
    if "connect-src 'none'" not in html:
        errors.append('Reference UI must disable network connections in its CSP')
    for asset in re.findall(r'(?:src|href)="([^"]+)"', html):
        if urlsplit(asset).scheme or asset.startswith('//'):
            errors.append('Reference UI contains an external resource')
        elif not (root / 'reference' / asset).is_file():
            errors.append('Missing reference asset: ' + asset)
    for name in ('app.js', 'core.js', 'demo.js'):
        text = (root / 'reference' / name).read_text(encoding='utf-8')
        if re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(', text):
            errors.append(name + ': reference implementation must not contact a network')
    return errors


def main():
    """Exit nonzero on consistency errors for use in local validation and CI."""
    root = Path(__file__).resolve().parents[1]
    errors = check(root)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Repository consistency checks passed (not a security or hardware audit).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
