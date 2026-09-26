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


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL",
    "google/gemma-3-27b-it:free",
)

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
        raise ValueError("No JSON object found in AI response.")

    return text[start : end + 1].strip()


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
                config={"response_mime_type": "application/json"},
            )

            content = getattr(response, "text", None)

            if not content:
                content = response.candidates[0].content.parts[0].text

            data = json.loads(extract_json_from_text(content))

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
                    f"HTTP {response.status_code}: {response.text[:500]}"
                )

            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(extract_json_from_text(content))

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

    headers = {"Authorization": PEXELS_API_KEY}
    terms = [keyword] + random.sample(
        BACKUP_KEYWORDS,
        len(BACKUP_KEYWORDS),
    )

    for term in terms:
        try:
            page = random.randint(1, 5)
            url = (
                "https://api.pexels.com/videos/search"
                f"?query={requests.utils.quote(term)}"
                f"&orientation=portrait&per_page=10&page={page}"
            )

            response = requests.get(
                url,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()

            for video in response.json().get("videos", []):
                video_id = video.get("id")

                if video_id in used_video_ids:
                    continue

                files = video.get("video_files") or []

                if not files:
                    continue

                selected = next(
                    (
                        item
                        for item in files
                        if item.get("height", 0) >= 1280
                    ),
                    files[0],
                )

                video_url = selected.get("link")

                if not video_url:
                    continue

                print(f"Downloading clip for: {term}")

                clip_response = requests.get(
                    video_url,
                    timeout=40,
                )
                clip_response.raise_for_status()

                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(clip_response.content)

                used_video_ids.add(video_id)
                return True

        except Exception as exc:
            print(f"Pexels fetch failed: {exc}")

    return False


def build_assets(storyboard):
    output_dir = Path("output")
    videos_dir = output_dir / "videos"
    audio_dir = output_dir / "audio"

    videos_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    processed = []

    for scene in storyboard.get("scenes", []):
        scene_id = scene["scene_id"]
        narration = scene["narration_text"]
        keyword = scene.get("search_keyword", "space galaxy")

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
            print(f"Voiceover failed for scene {scene_id}: {exc}")
            continue

        if fetch_pexels_video(keyword, video_path):
            processed.append(
                (
                    scene_id,
                    str(video_path),
                    str(audio_path),
                    narration,
                )
            )

    return processed


def add_caption_overlay(video_path, audio_path, caption_text, output_path):
    """Add caption with text overlay."""
    try:
        # Write caption to file to avoid quoting issues
        caption_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        caption_file.write(caption_text)
        caption_file.close()
        
        try:
            # FFmpeg drawtext filter
            filter_complex = (
                f"[0:v]scale=1080:1920,"
                f"drawtext=textfile='{caption_file.name}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=48:"
                f"fontcolor=white:"
                f"bordercolor=black:"
                f"borderw=3:"
                f"x=(w-text_w)/2:"
                f"y=h-250:"
                f"line_spacing=10[vout]"
            )
            
            command = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                output_path,
            ]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0:
                print(f"FFmpeg error: {result.stderr[-800:]}")
                return False
            
            if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
                print(f"Output missing")
                return False
            
            print(f"✅ Caption added")
            return True
        
        finally:
            if Path(caption_file.name).exists():
                os.remove(caption_file.name)
    
    except Exception as exc:
        print(f"Caption failed: {exc}")
        return False


def create_crossfade(scene1, scene2, output_path, duration=1.0):
    """Simple crossfade between scenes."""
    try:
        filter_complex = (
            f"[0:v][1:v]xfade=transition=fade:duration={duration}:offset=0[v];"
            f"[0:a][1:a]acrossfade=d={duration}[a]"
        )
        
        command = [
            "ffmpeg", "-y",
            "-i", scene1,
            "-i", scene2,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            output_path,
        ]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        return result.returncode == 0
    
    except Exception as exc:
        print(f"Crossfade failed: {exc}")
        return False


def apply_transitions(scene_paths):
    """Apply crossfade between scenes."""
    if len(scene_paths) <= 1:
        return scene_paths
    
    print(f"Applying transitions to {len(scene_paths)} scenes...")
    
    final_scenes = [scene_paths[0]]
    
    for i in range(1, len(scene_paths)):
        output_path = f"output/videos/transition_{i}.mp4"
        
        if create_crossfade(final_scenes[-1], scene_paths[i], output_path, 0.75):
            final_scenes.append(output_path)
            print(f"✅ Transition {i} created")
        else:
            print(f"⚠️ Transition {i} skipped")
            final_scenes.append(scene_paths[i])
    
    return final_scenes


def stitch_video(processed_scenes):
    """Create final reel."""
    if not processed_scenes:
        raise RuntimeError("No scenes processed.")

    scene_outputs = []

    for scene_id, video_path, audio_path, narration in processed_scenes:
        output_path = f"output/videos/captioned_{scene_id}.mp4"

        print(f"Processing scene {scene_id}...")

        if add_caption_overlay(video_path, audio_path, narration, output_path):
            scene_outputs.append(output_path)

    if not scene_outputs:
        raise RuntimeError("No captioned scenes created.")

    # Apply transitions
    if len(scene_outputs) > 1:
        scene_outputs = apply_transitions(scene_outputs)

    concat_list = Path("output/concat_list.txt")

    with concat_list.open("w") as file:
        for path in scene_outputs:
            file.write(f"file '{Path(path).resolve()}'\n")

    final_output = Path("output/final_reel.mp4")

    command = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(final_output),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("Final concat error:")
        print(result.stderr[-1500:])
        raise RuntimeError("Final concat failed.")

    if not final_output.exists() or final_output.stat().st_size == 0:
        raise RuntimeError("final_reel.mp4 not created.")

    print(f"🎉 FINAL REEL READY")
    return final_output


def main():
    print("Starting Reel Production...")

    storyboard = generate_storyboard(
        "What happens at the edge of the observable universe?"
    )

    print(f"Scenes: {len(storyboard.get('scenes', []))}")

    processed_scenes = build_assets(storyboard)

    print(f"Processed: {len(processed_scenes)}")

    final_output = stitch_video(processed_scenes)

    print(f"Done: {final_output.exists()}")


if __name__ == "__main__":
    main()
