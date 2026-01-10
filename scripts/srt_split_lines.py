#!/usr/bin/env python3
import sys
import re
from datetime import timedelta

def parse_time(t):
    h, m, s = t.replace(",", ".").split(":")
    return timedelta(hours=float(h), minutes=float(m), seconds=float(s))

def format_time(td):
    total_seconds = td.total_seconds()
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = total_seconds % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")

def split_line(text, max_words):
    words = text.split()
    lines = []
    for i in range(0, len(words), max_words):
        lines.append(" ".join(words[i:i + max_words]))
    return lines

if len(sys.argv) < 4:
    print("Uso: python3 srt_split_lines.py input.srt output.srt max_words [singleline]")
    sys.exit(1)

infile, outfile = sys.argv[1], sys.argv[2]
max_words = int(sys.argv[3])
singleline = len(sys.argv) > 4 and sys.argv[4].lower() == "singleline"

with open(infile, "r", encoding="utf-8") as f:
    content = f.read().strip()

entries = re.split(r"\n\s*\n", content)
new_entries = []
idx = 1

for entry in entries:
    lines = entry.strip().splitlines()
    if len(lines) < 3:
        continue

    times = lines[1]
    start, end = [parse_time(t) for t in re.split(r" *--> *", times)]
    duration = (end - start).total_seconds()

    text = " ".join(lines[2:])
    chunks = split_line(text, max_words)

    if singleline:
        # Divide o tempo total igualmente entre as partes
        per_chunk = duration / len(chunks)
        for i, chunk in enumerate(chunks):
            s = start + timedelta(seconds=i * per_chunk)
            e = start + timedelta(seconds=(i + 1) * per_chunk)
            new_entries.append(f"{idx}\n{format_time(s)} --> {format_time(e)}\n{chunk}\n")
            idx += 1
    else:
        # Mantém o tempo original e apenas quebra visualmente
        new_entries.append(f"{idx}\n{format_time(start)} --> {format_time(end)}\n" + "\n".join(chunks) + "\n")
        idx += 1

with open(outfile, "w", encoding="utf-8") as f:
    f.write("\n".join(new_entries))

print(f"✅ Novo arquivo salvo: {outfile}")
