"""Trusted quadratic animation template; data only, no generated executable code.

Artifacts are immutable and published only after ffprobe validation. A failed
new render never replaces an earlier result. No automatic task-level fallback:
callers must retain their prior successful result and label a failed revision.
"""
from __future__ import annotations

import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path

FPS = 12
WIDTH, HEIGHT = 640, 360


def validate_animation(spec):
    if not isinstance(spec, dict) or set(spec) - {'template', 'a', 'b', 'c', 'domain', 'duration_seconds'}:
        raise ValueError('Unknown animation fields')
    if spec.get('template') != 'quadratic_trace':
        raise ValueError('Only trusted quadratic_trace animation is supported')
    def number(value, limit):
        if type(value) not in (int, float) or abs(value) > limit or not math.isfinite(value):
            raise ValueError('Animation parameters must be bounded finite numbers')
        return float(value)
    a, b, c = [number(spec.get(key, default), 10) for key, default in [('a', 1), ('b', 0), ('c', 0)]]
    if abs(a) < .01:
        raise ValueError('Quadratic coefficient magnitude must be at least 0.01')
    domain = spec.get('domain', [-3, 3])
    if not isinstance(domain, list) or len(domain) != 2:
        raise ValueError('Domain must be [xmin,xmax]')
    xmin, xmax = [number(x, 10) for x in domain]
    if xmax - xmin < .1:
        raise ValueError('Domain must increase by at least 0.1')
    seconds = spec.get('duration_seconds', 6)
    if type(seconds) is not int or not 2 <= seconds <= 12:
        raise ValueError('Duration must be an integer from 2 to 12 seconds')
    return {'template': 'quadratic_trace', 'a': a, 'b': b, 'c': c,
            'domain': [xmin, xmax], 'duration_seconds': seconds}


def sample_quadratic(spec, count=201):
    spec = validate_animation(spec)
    if type(count) is not int or not 2 <= count <= 501:
        raise ValueError('Sample count must be between 2 and 501')
    lo, hi = spec['domain']
    a, b, c = (spec[k] for k in ('a', 'b', 'c'))
    return [(x, (a*x+b)*x+c, 2*a*x+b)
            for x in (lo+(hi-lo)*i/(count-1) for i in range(count))]


def probe_video(path, *, duration, runner, ffprobe):
    info = json.loads(runner([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                             '-count_frames', '-show_entries',
                             'stream=codec_name,width,height,nb_read_frames:format=duration',
                             '-of', 'json', str(path)]))
    streams = info.get('streams', [])
    if len(streams) != 1:
        raise RuntimeError('Animation has no single validated video stream')
    stream = streams[0]
    measured = float(info['format']['duration'])
    if (stream.get('codec_name') != 'h264' or stream.get('width') != WIDTH or stream.get('height') != HEIGHT
            or int(stream.get('nb_read_frames', -1)) != duration * FPS
            or not math.isfinite(measured) or abs(measured-duration) > .1):
        raise RuntimeError('Animation failed duration/codec/frame validation')
    return {'codec': 'h264', 'width': WIDTH, 'height': HEIGHT,
            'frames': duration*FPS, 'duration_seconds': measured}


def build_math_lesson(inputs):
    from . import media
    spec = validate_animation(inputs.get('animation'))
    tts = inputs.get('tts', 'none')
    if tts not in (None, 'none', {}, {'provider': 'none'}):
        raise ValueError('Trusted math animation currently supports silent captions only')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Math animation requires existing FFmpeg and ffprobe')
    from PIL import Image, ImageDraw, ImageFont
    # Fixed renderer text/font, never interpolate model-generated expressions.
    font = ImageFont.truetype(media.DEFAULT_FONT, 16)
    a, b, c = (spec[k] for k in ('a', 'b', 'c'))
    duration = spec['duration_seconds']
    lo, hi = spec['domain']
    points = sample_quadratic(spec)
    ys = [p[1] for p in points]
    vertex = -b/(2*a)
    if lo <= vertex <= hi:
        ys.append((a*vertex+b)*vertex+c)
    ymin, ymax = min(ys), max(ys)
    pad = max((ymax-ymin)*.12, .01)
    ymin, ymax = ymin-pad, ymax+pad
    xy = lambda x,y: (50+(x-lo)/(hi-lo)*550, 290-(y-ymin)/(ymax-ymin)*205)
    curve = [xy(x,y) for x,y,_ in points]
    formula = f'y = {a:g} x² + {b:g} x + {c:g}'
    captions = [('观察二次函数曲线，亮点沿 x 从左向右移动。', 0, duration/2),
                ('斜率由导数 2ax+b 计算；显示坐标是函数值，不是模型猜测。', duration/2, duration)]
    vtt = 'WEBVTT\n\n' + '\n\n'.join(f'{media._stamp(start)} --> {media._stamp(end)}\n{text}' for text,start,end in captions) + '\n'
    media.ARTIFACTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    media_id = uuid.uuid4().hex
    destination = media.ARTIFACTS/media_id
    with tempfile.TemporaryDirectory(prefix='math-', dir=media.ARTIFACTS) as staging:
        temp = Path(staging)
        frames = sample_quadratic(spec, duration*FPS)
        for index, (x,y,slope) in enumerate(frames):
            image = Image.new('RGB', (WIDTH, HEIGHT), '#10192a')
            draw = ImageDraw.Draw(image)
            draw.text((30,15), '二次函数：数值驱动动画', font=font, fill='white')
            draw.text((30,42), formula, font=font, fill='#81d7ed')
            draw.rectangle((50,85,600,290), outline='#526079')
            if lo <= 0 <= hi:
                px,_ = xy(0,0); draw.line((px,85,px,290), fill='#526079')
            if ymin <= 0 <= ymax:
                _,py = xy(0,0); draw.line((50,py,600,py), fill='#526079')
            draw.line(curve, fill='#668aff', width=3)
            px,py = xy(x,y)
            draw.ellipse((px-5,py-5,px+5,py+5), fill='#ffcc66')
            draw.text((30,310), f'x={x:.3f}   y={y:.3f}   dy/dx={slope:.3f}', font=font, fill='white')
            image.save(temp/f'{index:04}.png')
        video = temp/'lesson.mp4'
        media._run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-framerate', str(FPS),
                    '-i', str(temp/'%04d.png'), '-frames:v', str(len(frames)), '-an',
                    '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)])
        verified = probe_video(video, duration=duration, runner=media._run, ffprobe=ffprobe)
        (temp/'captions.vtt').write_text(vtt, encoding='utf-8')
        # Stage only final assets and atomically rename; failed attempts expose no partial media.
        final = temp/'publish'
        final.mkdir()
        video.replace(final/'lesson.mp4')
        (temp/'captions.vtt').replace(final/'captions.vtt')
        final.rename(destination)
    return {'kind': 'video_lesson', 'title': '二次函数数值动画', 'media_id': media_id,
            'video_url': f'/api/media/{media_id}/lesson.mp4',
            'subtitles_url': f'/api/media/{media_id}/captions.vtt', 'subtitles_vtt': vtt,
            'duration_seconds': duration, 'narration': 'none', 'renderer': 'trusted-quadratic-animation',
            'animation': spec, 'verification': verified, 'fallback_used': False,
            'limitations': ['Fixed trusted quadratic template, not generated Remotion/Manim code.',
                            'No narration; failed revisions do not replace earlier media.']}
