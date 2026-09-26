import os
import json
import random
import asyncio
from pathlib import Path

import requests
import subprocess
import edge_tts
from google import genai

# Retrieve API keys securely
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

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

    # 1. Try Gemini first
    if client_gemini:
        try:
            print("Attempting with Gemini API (gemini-2.0-flash)...")
            response = client_gemini.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{system_prompt}\n\n{user_prompt}",
                config={"response_mime_type": "application/json"},
            )

            content = getattr(response, "text", None)
            if not content:
                content = response.candidates[0].content.parts[0].text

            data = json.loads(extract_json_from_text(content))
            if isinstance(data, dict) and "scenes" in data:
                return data
        except Exception as e:
            print(f"Gemini failed: {e}")

    # 2. Try OpenRouter fallback second
    if OPENROUTER_API_KEY:
        try:
            print("Attempting with OpenRouter fallback...")
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            data = {
                "model": "google/gemma-2-9b-it:free",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            res = requests.post(url, headers=headers, json=data, timeout=30)
            res.raise_for_status()
            res_json = res.json()

            content = res_json["choices"][0]["message"]["content"]
            data = json.loads(extract_json_from_text(content))
            if isinstance(data, dict) and "scenes" in data:
                return data
        except Exception as e:
            print(f"OpenRouter failed: {e}")

    raise ValueError("All AI models and fallbacks failed to generate content.")


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
        except Exception as e:
            print(f"Fetch error: {e}")
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
            processed_scenes.append((s_id, video_path, audio_path))

    return processed_scenes


def stitch_video(processed_scenes):
    if not processed_scenes:
        print("❌ Error: No scenes were processed successfully.")
        return

    scene_outputs = []
    for s_id, v_path, a_path in processed_scenes:
        merged_path = f"output/videos/merged_{s_id}.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            v_path,
            "-i",
            a_path,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            merged_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            print(f"ffmpeg merge failed for scene {s_id}")
            continue
        scene_outputs.append(merged_path)

    if not scene_outputs:
        print("❌ Error: No scene videos could be merged.")
        return

    concat_list = "output/concat_list.txt"
    with open(concat_list, "w") as f:
        for p in scene_outputs:
            f.write(f"file '{os.path.abspath(p)}'\n")

    final_output = "output/final_reel.mp4"
    concat_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list,
        "-c",
        "copy",
        final_output,
    ]
    result = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print(f"🎉 FINAL REEL READY: {final_output}")
    else:
        print("❌ Error: Final reel assembly failed.")


def main():
    print("Starting Autonomous Reel Production Engine...")
    storyboard = generate_storyboard("What happens at the edge of the observable universe?")
    scenes = build_assets(storyboard)
    stitch_video(scenes)


if __name__ == "__main__":
    main()
