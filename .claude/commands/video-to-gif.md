# Video to GIF — Convert Video Files to Animated GIFs

Convert one or more video files (MOV, MP4, AVI, MKV, WEBM, etc.) to optimized animated GIFs using ffmpeg.

## Input
- `$ARGUMENTS` = space-separated list of video file paths, optionally followed by flags
- Supported flags:
  - `--fps <N>` — frames per second (default: 15)
  - `--width <N>` — output width in pixels, height auto-scaled (default: 480)
  - `--quality high` — use two-pass palette generation for better color quality (default: off, uses lanczos scaling)

Examples:
```
/path/to/video.mov
/path/to/a.mp4 /path/to/b.MOV
/path/to/video.mp4 --fps 10 --width 640
/path/to/video.mov --quality high
```

## AUTONOMOUS DIRECTIVE
This is a **fully automated pipeline**. The user will NOT be present.
- DO NOT use `EnterPlanMode` or `AskUserQuestion`
- DO NOT pause for user confirmation
- Execute end-to-end without stopping

## Step 0: Parse arguments and ensure ffmpeg is available

Parse `$ARGUMENTS` to extract:
1. **File paths** — all tokens that don't start with `--` and aren't flag values
2. **Flags** — `--fps`, `--width`, `--quality`

Defaults:
```
FPS=15
WIDTH=480
QUALITY="standard"
```

Check that ffmpeg is installed:
```bash
if ! command -v ffmpeg &>/dev/null; then
  echo "ffmpeg not found. Installing via Homebrew..."
  brew install ffmpeg
fi
ffmpeg -version | head -1
```

## Step 1: Validate input files

For each file path provided:
1. Verify the file exists
2. Verify it has a video extension (case-insensitive): `.mov`, `.mp4`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.wmv`, `.flv`
3. Print file info using ffprobe:
```bash
ffprobe -v quiet -print_format json -show_streams -show_format "$FILE"
```

If any file is missing or not a video, report the error and skip it (continue with remaining files).

## Step 2: Convert each video to GIF

For each valid video file, derive the output path by replacing the extension with `.gif` in the same directory.

### Standard quality (default):
```bash
ffmpeg -i "$INPUT" \
  -vf "fps=$FPS,scale=$WIDTH:-1:flags=lanczos" \
  -loop 0 \
  "$OUTPUT" -y
```

### High quality (two-pass with palette):
```bash
# Pass 1: Generate optimal palette
ffmpeg -i "$INPUT" \
  -vf "fps=$FPS,scale=$WIDTH:-1:flags=lanczos,palettegen=stats_mode=diff" \
  -y "/tmp/palette_$(basename "$INPUT").png"

# Pass 2: Use palette for conversion
ffmpeg -i "$INPUT" \
  -i "/tmp/palette_$(basename "$INPUT").png" \
  -lavfi "fps=$FPS,scale=$WIDTH:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5" \
  -loop 0 \
  "$OUTPUT" -y

# Cleanup palette
rm -f "/tmp/palette_$(basename "$INPUT").png"
```

Run conversions in **parallel** (multiple Bash tool calls) when there are multiple files.

## Step 3: Final output

Print a summary table:

```
| # | Input File          | Output GIF          | Duration | Size   | Dimensions |
|---|---------------------|---------------------|----------|--------|------------|
| 1 | video.mov           | video.gif           | 2.1s     | 591 KB | 480x480    |
| 2 | clip.mp4            | clip.gif            | 5.0s     | 1.9 MB | 480x270    |
```

For each output GIF, get size with:
```bash
ls -lh "$OUTPUT" | awk '{print $5}'
```

And dimensions with:
```bash
ffprobe -v quiet -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$OUTPUT"
```

Print paths to all generated GIFs so the user can easily find them.
