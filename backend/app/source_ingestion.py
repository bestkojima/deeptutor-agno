"""Bounded, offline caption ingestion. No URLs, local path reads or transcription.

Integration: ingest_source(data: bytes, filename='lesson.vtt') returns source
records accepted by task inputs.sources. A future upload endpoint must read at
most MAX_BYTES+1 bytes before calling this function and apply its own auth.
CLI: python -m app.source_ingestion /trusted/local/captions.vtt
PDF/OCR and raw audio/video ingestion deliberately remain unsupported here.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePath

MAX_BYTES = 2_000_000
MAX_CUES = 5000
MAX_CUE_CHARS = 20_000
MAX_DURATION_SECONDS = 7 * 24 * 3600


class IngestionError(ValueError):
    """An invalid or unsupported uploaded source, safe to report to the caller."""


def _timestamp(value: str, kind: str) -> float:
    pattern = r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})" if kind == 'vtt' else r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})"
    match = re.fullmatch(pattern, value)
    if not match:
        raise IngestionError('Invalid caption timestamp')
    hours, minutes, seconds, millis = match.groups()
    result = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
    if result > MAX_DURATION_SECONDS:
        raise IngestionError('Caption timestamp exceeds seven-day limit')
    return result


def ingest_source(data: bytes, *, filename: str) -> list[dict]:
    """Parse UTF-8 VTT/SRT bytes into exact text and timestamp source records.

    Cue markup is retained as inert source text, never rendered. Overlapping
    intervals are legal; cues must be ordered by start time. IDs bind to source
    content, avoiding collisions between distinct transcripts in one task.
    """
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise IngestionError('Source must contain 1–2000000 bytes')
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 255:
        raise IngestionError('A short source filename is required')
    if '/' in filename or '\\' in filename or ':' in filename or any(ord(c) < 32 for c in filename):
        raise IngestionError('Filename must be a name, not a path or URL')
    kind = PurePath(filename).suffix.lower().lstrip('.')
    if kind not in ('vtt', 'srt'):
        raise IngestionError('Only VTT/SRT are supported; PDF/OCR and raw audio/video transcription are not performed')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise IngestionError('Caption source must be UTF-8') from exc
    if '\x00' in text:
        raise IngestionError('NUL bytes are not allowed')
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    blocks = re.split(r'\n[ \t]*\n+', text)
    if kind == 'vtt':
        first = blocks.pop(0).splitlines() if blocks else []
        if not first or not re.fullmatch(r'WEBVTT(?:[ \t].*)?', first[0]) or '-->' in '\n'.join(first):
            raise IngestionError('WebVTT header and blank separator are required')
    digest = hashlib.sha256(data).hexdigest()[:24]
    result = []
    previous = -1.0
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        if kind == 'vtt' and (re.match(r'^NOTE(?:[ \t]|$)', lines[0]) or lines[0] in ('STYLE', 'REGION')):
            continue  # Metadata is never exposed as executable output.
        if kind == 'srt':
            if not re.fullmatch(r'\d+', lines[0]):
                raise IngestionError('SRT cue requires a numeric identifier')
            lines = lines[1:]
        elif '-->' not in lines[0]:
            lines = lines[1:]  # Optional VTT cue identifier.
        if len(lines) < 2:
            raise IngestionError('Caption cue is missing timing or text')
        match = re.fullmatch(r'(\S+)[ \t]+-->[ \t]+(\S+)(?:[ \t]+(.*))?', lines[0])
        if not match or (kind == 'srt' and match.group(3)):
            raise IngestionError('Invalid caption timing line')
        start, end = (_timestamp(stamp, kind) for stamp in match.groups()[:2])
        if end <= start or start < previous:
            raise IngestionError('Caption intervals must be positive and ordered by start time')
        body = '\n'.join(lines[1:])
        if not body.strip() or len(body) > MAX_CUE_CHARS or '-->' in body:
            raise IngestionError('Invalid or oversized caption text')
        previous = start
        result.append({'id': f'caption:{digest}:{len(result)+1}', 'title': filename,
                       'text': body, 'start_seconds': start, 'end_seconds': end})
        if len(result) > MAX_CUES:
            raise IngestionError('Source exceeds 5000 cues')
    if not result:
        raise IngestionError('No caption cues found; transcription is not performed')
    return result


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    try:
        # CLI-only path access is intentional. Do not expose this as an API path parameter.
        with args.file.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        print(json.dumps(ingest_source(data, filename=args.file.name), ensure_ascii=False, indent=2))
    except (OSError, IngestionError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
