import asyncio
import json
import os
import random
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import requests
from google import genai
from PIL import Image, ImageDraw, ImageFont


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.8-flash",
)

OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL",
    "google/gemma-3-27b-it:free",
)

client_gemini = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)


BACKUP_KEYWORDS = [
    "deep space 4k",
    "black hole accretion",
    "spinning galaxy vertical",
    "supernova explosion motion",
    "wormhole tunnel space",
    "neutron star cosmic",
]

used_video_ids = set()


def extract_json_from_text(text):
    if not text:
        raise ValueError("Empty AI response.")

    text = text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found.")

    return text[start:end + 1].strip()


def offline_storyboard(topic):
    narrations = [
        "What lies beyond the edge of everything we can see?",
        "The observable universe is only the region whose light has reached us.",
        "Far away, galaxies are moving so quickly that their light may never reach us.",
        "Beyond that horizon could be trillions of galaxies hidden forever from our view.",
        "The edge is not a wall. It is a limit on what information can reach us.",
        "Somewhere beyond it, the universe may continue without an edge at all.",
        "The observable universe is only our cosmic bubble.",
    ]

    keywords = [
        "deep space galaxy",
        "observable universe animation",
        "galaxy cluster space",
        "expanding universe",
        "cosmic horizon",
        "deep space stars",
        "spiral galaxy vertical",
    ]

    return {
        "project_name": "Cosmology_Reels",
        "topic": topic,
        "scenes": [
            {
                "scene_id": index,
                "duration_seconds": 8,
                "narration_text": narration,
                "search_keyword": keyword,
            }
            for index, (narration, keyword) in enumerate(
                zip(narrations, keywords),
                start=1,
            )
        ],
    }


def generate_storyboard(topic):
    system_prompt = """
You are an expert video producer for US Facebook Reels and YouTube Shorts.

Create a 60-second vertical 9:16 script about Space Mysteries.
Target audience: USA.
Language: English.
Tone: atmospheric, cinematic, and deep.

Return only valid JSON:
{
  "project_name": "Cosmology_Reels",
  "topic": "string",
  "scenes": [
    {
      "scene_id": 1,
      "duration_seconds": 5,
      "narration_text": "Engaging narration in English",
      "search_keyword": "black hole accretion disk"
    }
  ]
}
"""

    user_prompt = f"Generate a storyboard about: {topic}"

    if client_gemini:
        try:
            print(f"Trying Gemini: {GEMINI_MODEL}")

            response = client_gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"{system_prompt}\n\n{user_prompt}",
                config={
                    "response_mime_type": "application/json",
                },
            )

            content = getattr(response, "text", None)

            if not content:
                content = response.candidates[0].content.parts[0].text

            data = json.loads(
                extract_json_from_text(content)
            )

            if isinstance(data, dict) and data.get("scenes"):
                return data

        except Exception as exc:
            print(f"Gemini failed: {exc}")

    if OPENROUTER_API_KEY:
        try:
            print(f"Trying OpenRouter: {OPENROUTER_MODEL}")

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": (
                        "https://github.com/"
                        "Mohinurking/cosmo-shorts-bot"
                    ),
                    "X-Title": "Cosmo Shorts Bot",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    "response_format": {
                        "type": "json_object",
                    },
                },
                timeout=30,
            )

            if not response.ok:
                raise RuntimeError(
                    f"HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )

            content = response.json()["choices"][0]["message"]["content"]

            data = json.loads(
                extract_json_from_text(content)
            )

            if isinstance(data, dict) and data.get("scenes"):
                return data

        except Exception as exc:
            print(f"OpenRouter failed: {exc}")

    print("Using offline storyboard fallback.")
    return offline_storyboard(topic)


async def generate_voiceover(text, output_file):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    voice = edge_tts.Communicate(
        text,
        "en-US-ChristopherNeural",
    )

    await voice.save(str(output_path))


def fetch_pexels_video(keyword, output_file):
    if not PEXELS_API_KEY:
        print("PEXELS_API_KEY is missing.")
        return False

    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    search_terms = [keyword] + random.sample(
        BACKUP_KEYWORDS,
        len(BACKUP_KEYWORDS),
    )

    for term in search_terms:
        try:
            page = random.randint(1, 5)

            url = (
                "https://api.pexels.com/videos/search"
                f"?query={requests.utils.quote(term)}"
                "&orientation=portrait"
                "&per_page=10"
                f"&page={page}"
            )

            response = requests.get(
                url,
                headers=headers,
                timeout=20,
            )

            response.raise_for_status()

            videos = response.json().get("videos", [])

            for video in videos:
                video_id = video.get("id")

                if video_id in used_video_ids:
                    continue

                video_files = video.get("video_files") or []

                if not video_files:
                    continue

                selected_file = next(
                    (
                        item
                        for item in video_files
                        if item.get("height", 0) >= 1280
                    ),
                    video_files[0],
                )

                video_url = selected_file.get("link")

                if not video_url:
                    continue

                print(f"Downloading Pexels video: {term}")

                clip_response = requests.get(
                    video_url,
                    timeout=40,
                )

                clip_response.raise_for_status()

                output_path = Path(output_file)
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_path.write_bytes(
                    clip_response.content
                )

                used_video_ids.add(video_id)

                return True

        except Exception as exc:
            print(f"Pexels fetch failed: {exc}")

    return False


def build_assets(storyboard):
    output_dir = Path("output")
    videos_dir = output_dir / "videos"
    audio_dir = output_dir / "audio"

    videos_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    processed_scenes = []

    for scene in storyboard.get("scenes", []):
        scene_id = scene["scene_id"]
        narration = scene["narration_text"]
        keyword = scene.get(
            "search_keyword",
            "space galaxy",
        )

        audio_path = audio_dir / f"scene_{scene_id}.mp3"
        video_path = videos_dir / f"scene_{scene_id}.mp4"

        try:
            asyncio.run(
                generate_voiceover(
                    narration,
                    audio_path,
                )
            )
        except Exception as exc:
            print(
                f"Voiceover failed for scene "
                f"{scene_id}: {exc}"
            )
            continue

        if fetch_pexels_video(
            keyword,
            video_path,
        ):
            processed_scenes.append(
                (
                    scene_id,
                    str(video_path),
                    str(audio_path),
                    narration,
                )
            )

    return processed_scenes


def wrap_caption_text(
    draw,
    text,
    font,
    max_width,
):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = (
            f"{current_line} {word}".strip()
        )

        bbox = draw.textbbox(
            (0, 0),
            test_line,
            font=font,
        )

        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)

            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def create_caption_image(caption_text):
    """
    Creates a transparent 1080x1920 caption layer.

    The caption is wrapped inside a safe width and
    placed near the bottom without leaving the screen.
    """

    canvas_width = 1080
    canvas_height = 1920

    image = Image.new(
        "RGBA",
        (canvas_width, canvas_height),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    font_path = (
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans-Bold.ttf"
    )

    try:
        font = ImageFont.truetype(
            font_path,
            44,
        )
    except Exception:
        font = ImageFont.load_default()

    safe_width = 880
    horizontal_padding = 42
    vertical_padding = 28
    line_spacing = 12

    lines = wrap_caption_text(
        draw,
        caption_text,
        font,
        safe_width,
    )

    line_heights = []

    for line in lines:
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
        )
        line_heights.append(
            bbox[3] - bbox[1]
        )

    text_height = (
        sum(line_heights)
        + line_spacing * max(0, len(lines) - 1)
    )

    box_width = safe_width + horizontal_padding * 2
    box_height = text_height + vertical_padding * 2

    # Safe bottom position.
    # The box never extends beyond 1920px.
    box_x = (canvas_width - box_width) // 2
    box_y = canvas_height - box_height - 190

    box_y = max(
        100,
        min(
            box_y,
            canvas_height - box_height - 80,
        ),
    )

    draw.rounded_rectangle(
        (
            box_x,
            box_y,
            box_x + box_width,
            box_y + box_height,
        ),
        radius=28,
        fill=(0, 0, 0, 145),
    )

    current_y = box_y + vertical_padding

    for line, line_height in zip(
        lines,
        line_heights,
    ):
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
        )

        text_width = bbox[2] - bbox[0]
        text_x = (
            canvas_width - text_width
        ) // 2

        # Black outline/shadow
        draw.text(
            (text_x + 3, current_y + 3),
            line,
            font=font,
            fill=(0, 0, 0, 255),
        )

        # Main white text
        draw.text(
            (text_x, current_y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
        )

        current_y += line_height + line_spacing

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".png",
        delete=False,
    )

    temp_file.close()

    image.save(temp_file.name)

    return temp_file.name


def get_video_duration(video_path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:"
        "nokey=1:novalue=1",
        video_path,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    try:
        return max(
            1.0,
            float(result.stdout.strip()),
        )
    except Exception:
        return 8.0


def add_caption_overlay(
    video_path,
    audio_path,
    caption_text,
    output_path,
):
    """
    Add a safe-position caption layer with
    fade-in and fade-out animation.
    """

    caption_image = None

    try:
        video_duration = get_video_duration(
            video_path
        )

        caption_image = create_caption_image(
            caption_text
        )

        fade_duration = min(
            0.45,
            video_duration / 4,
        )

        fade_out_start = max(
            0.0,
            video_duration - fade_duration,
        )

        filter_complex = (
            "[0:v]"
            "scale=1080:1920:"
            "force_original_aspect_ratio=decrease,"
            "pad=1080:1920:"
            "(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
            "[base];"

            "[1:v]"
            "format=rgba,"
            f"fade=t=in:st=0:d={fade_duration}:alpha=1,"
            f"fade=t=out:st={fade_out_start}:"
            f"d={fade_duration}:alpha=1"
            "[caption];"

            "[base][caption]"
            "overlay=0:0:shortest=1"
            "[vout]"
        )

        command = [
            "ffmpeg",
            "-y",

            # Main video
            "-i",
            video_path,

            # Animated transparent caption image
            "-loop",
            "1",
            "-i",
            caption_image,

            # Generated voiceover
            "-i",
            audio_path,

            "-filter_complex",
            filter_complex,

            "-map",
            "[vout]",
            "-map",
            "2:a:0",

            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",

            "-c:a",
            "aac",
            "-b:a",
            "192k",

            "-pix_fmt",
            "yuv420p",
            "-shortest",

            output_path,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print("Animated caption FFmpeg error:")
            print(result.stderr[-2500:])
            return False

        output_file = Path(output_path)

        if (
            not output_file.exists()
            or output_file.stat().st_size == 0
        ):
            print(
                f"Caption output missing: {output_path}"
            )
            return False

        print(
            f"Animated caption created: {output_path}"
        )

        return True

    except Exception as exc:
        print(f"Caption generation failed: {exc}")
        return False

    finally:
        if caption_image and os.path.exists(
            caption_image
        ):
            os.remove(caption_image)


def stitch_video(processed_scenes):
    """
    Join captioned scenes without transitions.
    """

    if not processed_scenes:
        raise RuntimeError(
            "No scenes were processed."
        )

    scene_outputs = []

    for (
        scene_id,
        video_path,
        audio_path,
        narration,
    ) in processed_scenes:
        output_path = (
            f"output/videos/captioned_{scene_id}.mp4"
        )

        print(
            f"Processing scene {scene_id}..."
        )

        if add_caption_overlay(
            video_path,
            audio_path,
            narration,
            output_path,
        ):
            scene_outputs.append(output_path)

    if not scene_outputs:
        raise RuntimeError(
            "No captioned scenes were created."
        )

    concat_list = Path(
        "output/concat_list.txt"
    )

    with concat_list.open("w") as file:
        for path in scene_outputs:
            file.write(
                f"file '{Path(path).resolve()}'\n"
            )

    final_output = Path(
        "output/final_reel.mp4"
    )

    # No xfade and no transition.
    # Re-encode all scenes consistently to avoid glitches.
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),

        "-vf",
        (
            "scale=1080:1920:"
            "force_original_aspect_ratio=decrease,"
            "pad=1080:1920:"
            "(ow-iw)/2:(oh-ih)/2,"
            "format=yuv420p"
        ),

        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",

        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-b:a",
        "192k",

        str(final_output),
    ]

    print(
        "Creating final reel without transitions..."
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=240,
    )

    if result.returncode != 0:
        print("Final FFmpeg error:")
        print(result.stderr[-3000:])
        raise RuntimeError(
            "Final reel creation failed."
        )

    if (
        not final_output.exists()
        or final_output.stat().st_size == 0
    ):
        raise RuntimeError(
            "final_reel.mp4 was not created."
        )

    print(
        f"FINAL REEL READY: {final_output}"
    )

    return final_output


def main():
    print(
        "Starting Reel Production..."
    )

    storyboard = generate_storyboard(
        "What happens at the edge of "
        "the observable universe?"
    )

    print(
        "Storyboard scenes: "
        f"{len(storyboard.get('scenes', []))}"
    )

    processed_scenes = build_assets(
        storyboard
    )

    print(
        f"Processed scenes: "
        f"{len(processed_scenes)}"
    )

    final_output = stitch_video(
        processed_scenes
    )

    print(
        f"Output exists: "
        f"{final_output.exists()}"
    )

    print(
        f"Output size: "
        f"{final_output.stat().st_size} bytes"
    )


if __name__ == "__main__":
    main()
