from pathlib import Path
import re

SOURCE = Path("turks_nederland_verified.m3u")
OUTPUT = Path("turks_nederland_setiptv.m3u")
REPORT = Path("setiptv_validation.txt")

if not SOURCE.exists():
    raise SystemExit(f"Missing source playlist: {SOURCE}")

raw = SOURCE.read_text(encoding="utf-8-sig")
src_lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

out = []
removed = []
channel_count = 0
current_channel = None

for line_no, line in enumerate(src_lines, start=1):
    s = line.strip()

    if not s:
        continue

    if s.startswith("#EXTVLCOPT:"):
        removed.append((line_no, current_channel or "(unknown)", s))
        continue

    # Remove human-readable separator comments if any slipped into the source.
    if re.fullmatch(r"#\s*=+\s*.*", s):
        continue

    if s.startswith("#EXTINF:"):
        channel_count += 1
        # Display name is after the last comma in the EXTINF line.
        current_channel = s.rsplit(",", 1)[-1].strip() or f"channel-{channel_count}"

    out.append(s)

# Validate the simplified structure:
errors = []
if not out or out[0] != "#EXTM3U":
    errors.append("First line is not #EXTM3U")

extinf_count = 0
for i, line in enumerate(out):
    if line.startswith("#EXTINF:"):
        extinf_count += 1
        if i + 1 >= len(out) or not out[i + 1].startswith(("http://", "https://")):
            errors.append(f"EXTINF at output line {i+1} is not followed directly by an HTTP(S) URL")

if extinf_count != channel_count:
    errors.append(f"Count mismatch: parsed {channel_count} channels but output has {extinf_count} EXTINF entries")

# UTF-8 without BOM, CRLF for maximum compatibility with simple M3U readers.
OUTPUT.write_bytes(("\r\n".join(out) + "\r\n").encode("utf-8"))

report = [
    "SETIPTV playlist validation",
    "===========================",
    f"Source: {SOURCE.name}",
    f"Output: {OUTPUT.name}",
    f"Channel entries in source: {channel_count}",
    f"Channel entries in output: {extinf_count}",
    f"EXTVLCOPT directives removed: {len(removed)}",
    f"Structural errors: {len(errors)}",
    "",
]

if removed:
    report.append("Removed EXTVLCOPT directives:")
    for line_no, channel, directive in removed:
        report.append(f"- source line {line_no}: {channel}: {directive}")
    report.append("")

if errors:
    report.append("ERRORS:")
    report.extend(f"- {e}" for e in errors)
else:
    report.append("Result: structurally valid simplified M3U.")
    report.append("")
    report.append("Compatibility note: channels whose playback depended on a User-Agent/Referer in EXTVLCOPT may no longer play in clients that do not reproduce those headers.")

REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

if errors:
    raise SystemExit("\n".join(errors))

print(f"Created {OUTPUT} with {extinf_count} channel entries.")
print(f"Removed {len(removed)} EXTVLCOPT directives.")
