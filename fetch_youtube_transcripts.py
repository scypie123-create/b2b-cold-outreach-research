"""
Download YouTube transcripts into Markdown files.

Install dependencies:
    python -m pip install youtube-transcript-api

Run the script with one or more YouTube video URLs:
    python fetch_youtube_transcripts.py "https://www.youtube.com/watch?v=VIDEO_ID"
    python fetch_youtube_transcripts.py "https://youtu.be/VIDEO_ID" "https://www.youtube.com/watch?v=ANOTHER_ID"

Output:
    Markdown files are saved inside research/youtube-transcripts/

Note:
    The script uses youtube-transcript-api for transcript text and YouTube's
    public oEmbed endpoint for basic video metadata. If metadata lookup fails,
    the transcript still saves with "Unknown title" or "Unknown channel".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


OUTPUT_DIR = Path("research") / "youtube-transcripts"


def extract_video_id(url: str) -> str:
    """Extract a YouTube video ID from common YouTube URL formats."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")

    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            video_id = parsed.path.strip("/").split("/")[1]
        else:
            video_id = ""
    else:
        video_id = ""

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(f"Could not find a valid YouTube video ID in: {url}")

    return video_id


def fetch_metadata(url: str) -> tuple[str, str]:
    """Fetch video title and channel name from YouTube oEmbed."""
    oembed_url = f"https://www.youtube.com/oembed?url={quote(url)}&format=json"

    try:
        with urlopen(oembed_url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return "Unknown title", "Unknown channel"

    title = payload.get("title") or "Unknown title"
    channel = payload.get("author_name") or "Unknown channel"
    return title, channel


def fetch_transcript(video_id: str) -> str:
    """Download transcript text for a video."""
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        entries = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        entries = YouTubeTranscriptApi().fetch(video_id)

    return "\n".join(clean_text(get_transcript_text(entry)) for entry in entries).strip()


def get_transcript_text(entry: object) -> str:
    """Read transcript text from old dict entries or newer snippet objects."""
    if isinstance(entry, dict):
        return str(entry.get("text", ""))

    return str(getattr(entry, "text", ""))


def clean_text(text: str) -> str:
    """Normalize transcript snippets for Markdown output."""
    return " ".join(text.replace("\n", " ").split())


def slugify(value: str, fallback: str) -> str:
    """Create a readable, filesystem-safe filename stem."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug[:80] or fallback


def build_markdown(title: str, channel: str, url: str, transcript: str) -> str:
    """Build the Markdown document for one transcript."""
    return (
        f"# {title}\n\n"
        f"- **Channel:** {channel}\n"
        f"- **URL:** {url}\n\n"
        "## Transcript\n\n"
        f"{transcript}\n"
    )


def build_failed_markdown(
    title: str,
    channel: str,
    url: str,
    attempted_on: str,
    error: Exception,
) -> str:
    """Build the Markdown document for a transcript retrieval failure."""
    return (
        f"# {title}\n\n"
        f"- **Channel:** {channel}\n"
        f"- **URL:** {url}\n"
        f"- **Date attempted:** {attempted_on}\n\n"
        "## Transcript\n\n"
        "Automatic transcript retrieval failed.\n\n"
        "## Exact API Error\n\n"
        f"{type(error).__name__}: {error}\n\n"
        "## Suggested Next Step\n\n"
        "Open the video on YouTube and check whether captions or a transcript are "
        "available manually. If they are available, copy the transcript into this "
        "file; if they are not available, choose another relevant video from the "
        "same expert that has captions enabled.\n"
    )


def ensure_output_dir() -> None:
    """Create the output directory, unless a file already exists at that path."""
    if OUTPUT_DIR.exists() and not OUTPUT_DIR.is_dir():
        raise FileExistsError(
            f"{OUTPUT_DIR} exists but is a file. Rename or remove it, then run this script again."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_transcript(url: str) -> Path:
    """Download and save one video's transcript."""
    video_id = extract_video_id(url)
    title, channel = fetch_metadata(url)
    filename = f"{slugify(title, video_id)}-{video_id}.md"
    output_path = OUTPUT_DIR / filename

    try:
        transcript = fetch_transcript(video_id)
    except (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        CouldNotRetrieveTranscript,
    ) as error:
        output_path.write_text(
            build_failed_markdown(title, channel, url, date.today().isoformat(), error),
            encoding="utf-8",
        )
        print(f"Transcript unavailable; saved failure notes: {output_path}")
        return output_path

    output_path.write_text(
        build_markdown(title, channel, url, transcript),
        encoding="utf-8",
    )
    return output_path


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube transcripts as Markdown files."
    )
    parser.add_argument("urls", nargs="+", help="One or more YouTube video URLs.")
    return parser.parse_args(argv)


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    try:
        ensure_output_dir()
    except FileExistsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    exit_code = 0
    for url in args.urls:
        try:
            saved_path = save_transcript(url)
        except (
            ValueError,
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
            CouldNotRetrieveTranscript,
        ) as error:
            print(f"Failed to download transcript for {url}: {error}", file=sys.stderr)
            exit_code = 1
        else:
            print(f"Saved transcript: {saved_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
