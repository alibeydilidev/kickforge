"""
KickForge Clip CLI.

Commands:
    kickforge-clip watch  — live heat detection during a stream
    kickforge-clip export — post-stream batch export
    kickforge-clip format — convert a clip to 9:16 vertical
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kickforge-clip",
        description="KickForge clip pipeline — detect, cut, format, export.",
    )
    sub = parser.add_subparsers(dest="command")

    # watch
    watch_cmd = sub.add_parser("watch", help="Live heat detection (requires running KickApp)")
    watch_cmd.add_argument("--threshold", type=float, default=5.0, help="Heat threshold")
    watch_cmd.add_argument("--window", type=float, default=60.0, help="Window in seconds")
    watch_cmd.add_argument("--output", default="./clips", help="Output directory")

    # export
    export_cmd = sub.add_parser("export", help="Export clips from a recording + moments file")
    export_cmd.add_argument("--input", required=True, help="Video file path")
    export_cmd.add_argument("--moments", required=True, help="JSON moments file")
    export_cmd.add_argument("--output", default="./export", help="Export directory")
    export_cmd.add_argument("--top", type=int, default=5, help="Top N clips to export")
    export_cmd.add_argument("--discord", default="", help="Discord webhook URL")

    # format
    fmt_cmd = sub.add_parser("format", help="Convert a clip to 9:16 vertical format")
    fmt_cmd.add_argument("--input", required=True, help="Input clip path")
    fmt_cmd.add_argument("--output", required=True, help="Output path")
    fmt_cmd.add_argument("--width", type=int, default=1080, help="Output width")
    fmt_cmd.add_argument("--height", type=int, default=1920, help="Output height")

    args = parser.parse_args()

    if args.command == "watch":
        _cmd_watch(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "format":
        _cmd_format(args)
    else:
        parser.print_help()


def _cmd_watch(args: argparse.Namespace) -> None:
    print(f"Heat detection mode (threshold={args.threshold}, window={args.window}s)")
    print(f"Output: {args.output}")
    print("This command requires a running KickApp with EventBus.")
    print("Use the HeatDetector class programmatically in your bot script.")


def _cmd_export(args: argparse.Namespace) -> None:
    import asyncio
    from kickforge_clip.clipper import Clipper, check_ffmpeg
    from kickforge_clip.detector import HeatMoment
    from kickforge_clip.exporter import ClipExporter

    if not check_ffmpeg():
        print("Error: FFmpeg not found. Install FFmpeg first.")
        sys.exit(1)

    # Load moments
    try:
        with open(args.moments) as f:
            raw_moments = json.load(f)
    except Exception as exc:
        print(f"Error loading moments file: {exc}")
        sys.exit(1)

    moments = [
        HeatMoment(
            timestamp=m["timestamp"],
            score=m["score"],
            messages_per_second=m.get("mps", 0),
            unique_chatters=m.get("unique_chatters", 0),
        )
        for m in raw_moments
    ]

    # Cut clips
    clipper = Clipper(input_path=args.input, output_dir=args.output)
    clip_paths = []
    for moment in moments:
        result = clipper.cut(moment.timestamp)
        if result.success:
            clip_paths.append(result.output_path)
        else:
            print(f"Warning: Failed to cut clip at {moment.timestamp:.0f}s: {result.error}")
            clip_paths.append("")

    # Filter out failed clips
    valid = [(m, p) for m, p in zip(moments, clip_paths) if p]
    if not valid:
        print("No clips were extracted successfully.")
        sys.exit(1)

    valid_moments, valid_paths = zip(*valid)

    # Export top N
    exporter = ClipExporter(output_dir=args.output)
    exported = exporter.export(list(valid_moments), list(valid_paths), top_n=args.top)

    print(f"Exported {len(exported)} clips to {args.output}/")
    for clip in exported:
        print(f"  #{clip.rank} — score {clip.score:.0f} — {clip.path}")

    # Discord notification
    if args.discord:
        asyncio.run(ClipExporter.notify_discord(exported, args.discord))


def _cmd_format(args: argparse.Namespace) -> None:
    from kickforge_clip.formatter import format_vertical

    result = format_vertical(
        input_path=args.input,
        output_path=args.output,
        width=args.width,
        height=args.height,
    )
    if result.success:
        print(f"Formatted: {result.output_path}")
    else:
        print(f"Error: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
