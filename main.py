import os
import json
import random
import asyncio
from pathlib import Path

import requests
import subprocess
import edge_tts
from google import genai
from PIL import Image, ImageDraw, ImageFont
import tempfile

# Retrieve API keys and provider settings securely
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")

# Initialize Gemini Client using modern SDK
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

BACKUP_KEYWORDS = [
    "deep space 4k",
    "black hole accretion",
    "spinning galaxy vertical",
    "supernova explosion motion",
    "wormhole tunnel space",
    "neutron star cosmic",
]

used_video_ids = set()
storyboard = None


def extract_json_from_text(text):
    if text is None:
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
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return text.strip()


def offline_storyboard(topic):
    """Last-resort storyboard so a temporary AI outage does not fail the job."""
    narrations = [
        "What lies beyond the edge of everything we can see?",
        "The observable universe is not the entire universe. It is only the region whose light has reached us.",
        "Far away, galaxies are moving so quickly that their light will never catch up with cosmic expansion.",
        "Beyond that horizon may be trillions of galaxies, hidden forever from our view.",
        "The strange truth is that the edge is not a wall. It is a limit on what information can reach us.",
        "And somewhere beyond it, the universe may continue without an edge at all.",
        "The observable universe is only our cosmic bubble. What exists outside it remains one of space's greatest mysteries.",
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
            for index, (narration, keyword) in enumerate(zip(narrations, keywords), 1)
        ],
    }


def generate_storyboard(topic):
    system_prompt = """
    You are an expert video producer for US Facebook Reels / Youtube Shorts.
    Create a 60-second vertical (9:16) script about Space Mysteries.
    Target Audience: USA. Language: English. Tone: Atmospheric, cinematic, deep.

    Return STRICTLY a JSON object with this structure:
    {
      "project_name": "Cosmology_Reels",
      "topic": "string",
      "scenes": [
        {
          "scene_id": 1,
          "duration_seconds": 5,
          "narration_text": "Engaging hook line in English...",
          "search_keyword": "black hole accretion disk"
        }
      ]
    }
    """
    user_prompt = f"Generate a storyboard about: {topic}"

    if client_gemini:
        try:
            print(f"Attempting with Gemini API ({GEMINI_MODEL})...")
            response = client_gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"{system_prompt}\n\n{user_prompt}",
                config={"response_mime_type": "application/json"},
            )

            content = getattr(response, "text", None)
            if not content:
                content = response.candidates[0].content.parts[0].text

            data = json.loads(extract_json_from_text(content))
            if isinstance(data, dict) and "scenes" in data:
                return data
        except Exception as exc:
            print(f"Gemini failed: {exc}")

    if OPENROUTER_API_KEY:
        try:
            print(f"Attempting with OpenRouter ({OPENROUTER_MODEL})...")
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Mohinurking/cosmo-shorts-bot",
                    "X-Title": "Cosmo Shorts Bot",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            if not response.ok:
                raise RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:1000]}"
                )

            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(extract_json_from_text(content))
            if isinstance(data, dict) and "scenes" in data:
                return data
        except Exception as exc:
            print(f"OpenRouter failed: {exc}")

    print("AI providers unavailable; using offline storyboard fallback.")
    return offline_storyboard(topic)


async def generate_voiceover(text, output_file):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await communicate.save(str(output_path))


def fetch_pexels_video(keyword, output_file):
    global used_video_ids
    if not PEXELS_API_KEY:
        return False

    headers = {"Authorization": PEXELS_API_KEY}
    search_terms = [keyword] + random.sample(BACKUP_KEYWORDS, len(BACKUP_KEYWORDS))

    for term in search_terms:
        page = random.randint(1, 5)
        query = requests.utils.quote(term)
        url = (
            f"https://api.pexels.com/videos/search?query={query}"
            f"&orientation=portrait&per_page=10&page={page}"
        )
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            videos = res.json().get("videos", [])

            for video in videos:
                v_id = video.get("id")
                if v_id in used_video_ids:
                    continue

                v_files = video.get("video_files") or []
                if not v_files:
                    continue

                hd_file = next(
                    (f for f in v_files if f.get("height", 0) >= 1280),
                    v_files[0],
                )
                video_url = hd_file.get("link")
                if not video_url:
                    continue

                print(f"Downloading Pexels clip (ID: {v_id}) for '{term}'...")
                clip_response = requests.get(video_url, timeout=30)
                clip_response.raise_for_status()

                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(clip_response.content)

                used_video_ids.add(v_id)
                return True
        except Exception as exc:
            print(f"Fetch error: {exc}")
    return False


def build_assets(storyboard):
    output_base = Path("output")
    (output_base / "videos").mkdir(parents=True, exist_ok=True)
    (output_base / "audio").mkdir(parents=True, exist_ok=True)
    processed_scenes = []

    for scene in storyboard.get("scenes", []):
        s_id = scene["scene_id"]
        narration = scene["narration_text"]
        keyword = scene.get("search_keyword", "space galaxy")

        audio_path = str(output_base / "audio" / f"scene_{s_id}.mp3")
        try:
            asyncio.run(generate_voiceover(narration, audio_path))
        except Exception as exc:
            print(f"Voiceover generation failed for scene {s_id}: {exc}")
            continue

        video_path = str(output_base / "videos" / f"scene_{s_id}.mp4")
        if fetch_pexels_video(keyword, video_path):
            processed_scenes.append((s_id, video_path, audio_path, narration))

    return processed_scenes


def add_caption_overlay(video_path, audio_path, caption_text, output_path, duration=8):
    """Add caption text overlay using ffmpeg and PIL."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            caption_image_path = tmp.name

        # Create caption image using PIL
        img_width, img_height = 1080, 1920
        img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_size = 50
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        # Wrap text
        max_chars_per_line = 20
        lines = []
        words = caption_text.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= max_chars_per_line:
                current_line += word + " "
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())

        y_offset = img_height - 300
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (img_width - text_width) // 2
            y = y_offset + (i * 80)

            for adj_x in [-2, -1, 0, 1, 2]:
                for adj_y in [-2, -1, 0, 1, 2]:
                    draw.text((x + adj_x, y + adj_y), line, font=font, fill=(0, 0, 0, 255))

            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

        img.save(caption_image_path)
        print(f"Caption image created: {caption_image_path}")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-loop", "1", "-i", caption_image_path,
            "-c:v", "libx264", "-c:a", "aac",
            "-filter_complex", "[0:v]scale=1080:1920[v];[v][1:v]overlay=0:0:shortest=1[vout]",
            "-map", "[vout]", "-map", "0:a", "-shortest",
            "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-b:a", "192k", output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"Caption added successfully: {output_path}")
        else:
            print(f"FFmpeg caption error: {result.stderr}")

        if os.path.exists(caption_image_path):
            os.remove(caption_image_path)

        return result.returncode == 0
    except Exception as exc:
        print(f"Caption overlay exception: {exc}")
        return False


def stitch_video(processed_scenes):
    """Create final reel with captions using ffmpeg."""
    if not processed_scenes:
        print("❌ Error: No scenes were processed successfully.")
        return

    scene_outputs = []

    for s_id, v_path, a_path, narration in processed_scenes:
        try:
            captioned_path = f"output/videos/captioned_{s_id}.mp4"
            print(f"Processing scene {s_id}...")
            if add_caption_overlay(v_path, a_path, narration, captioned_path):
                scene_outputs.append(captioned_path)
                print(f"✅ Scene {s_id} processed with caption.")
            else:
                print(f"❌ Failed to add caption to scene {s_id}")
        except Exception as exc:
            print(f"Scene processing exception {s_id}: {exc}")

    if not scene_outputs:
        print("❌ Error: No scene videos could be created.")
        return

    print(f"Total scenes with captions: {len(scene_outputs)}")

    concat_list = "output/concat_list.txt"
    with open(concat_list, "w") as f:
        for path in scene_outputs:
            f.write(f"file '{os.path.abspath(path)}'\n")

    print(f"Concat list created: {concat_list}")

    final_output = "output/final_reel.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", final_output,
    ]

    print("Running final concat...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"🎉 FINAL REEL READY: {final_output}")
    else:
        print(f"❌ FFmpeg concat error: {result.stderr}")

    final_file = Path(final_output)
    if not final_file.exists():
        raise FileNotFoundError("final_reel.mp4 was not created")

    return final_file


def main():
    global storyboard
    print("Starting Autonomous Reel Production Engine...")
    storyboard = generate_storyboard("What happens at the edge of the observable universe?")
    print(f"Storyboard generated with {len(storyboard.get('scenes', []))} scenes")
    scenes = build_assets(storyboard)
    print(f"Assets built: {len(scenes)} scenes")
    output_file = stitch_video(scenes)
    print(f"Final output exists: {output_file.exists() if output_file else False}")


if __name__ == "__main__":
    main()
