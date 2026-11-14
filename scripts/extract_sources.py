"""Convert an existing local PDF text layer or WebVTT into task source JSON."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def seconds(stamp):
    parts = stamp.replace(",", ".").split(":")
    return sum(float(part)*60**power for power, part in enumerate(reversed(parts)))


def extract(path):
    if path.suffix.lower() == ".pdf":
        proc = subprocess.run(["pdftotext","-enc","UTF-8",str(path.resolve()),"-"],
                              capture_output=True, check=True, timeout=45)
        return [{"id":f"p{i}","title":path.name,"page":i,"text":text.strip()}
                for i,text in enumerate(proc.stdout.decode("utf-8").split("\f"),1) if text.strip()]
    if path.suffix.lower() not in {".vtt",".srt"}:
        raise ValueError("Input must be PDF, WebVTT or SRT")
    content=path.read_text(encoding="utf-8-sig")
    sources=[]
    for block in re.split(r"\r?\n\s*\r?\n",content):
        lines=block.splitlines()
        for i,line in enumerate(lines[:2]):
            match=re.fullmatch(r"([\d:.,]+)\s+-->\s+([\d:.,]+)(?:\s+.*)?",line.strip())
            if match and lines[i+1:]:
                start,end=map(seconds,match.groups())
                if start<0 or end<start:
                    raise ValueError("Invalid subtitle interval")
                sources.append({"id":f"cue{len(sources)+1}","title":path.name,"start_seconds":start,
                                "end_seconds":end,"text":"\n".join(lines[i+1:])})
                break
    return sources


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",type=Path)
    args=parser.parse_args()
    rows=extract(args.file)
    if not rows:
        parser.error("No text layer or caption cues found; OCR/transcription is not performed.")
    print(json.dumps(rows,indent=2,ensure_ascii=False))
