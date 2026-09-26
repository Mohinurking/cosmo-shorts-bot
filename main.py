import os
import json
import random
import asyncio
from pathlib import Path

import requests
import subprocess
import edge_tts
from google import genai
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

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
storyboard = None  # Global variable for storyboard


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


def add_caption_to_clip(clip, text):
    """Add text caption overlay to video clip with fade in/out effect."""
    try:
        txt_clip = (
            TextClip(
                text,
                fontsize=32,
                color="white",
                font="DejaVu-Sans-Bold",
                stroke_color="black",
                stroke_width=2,
                method="caption",
                size=(int(clip.w * 0.85), None),
            )
            .set_position(("center", 0.82))
            .set_duration(clip.duration)
            .crossfadein(0.2)
            .crossfadeout(0.2)
        )
        return CompositeVideoClip([clip, txt_clip])
    except Exception as exc:
        print(f"Caption overlay failed: {exc}. Returning original clip.")
        return clip


def apply_scene_transition(clip1, clip2, duration=0.6):
    """Apply crossfade transition between two clips."""
    try:
        clip1_faded = clip1.crossfadeout(duration)
        clip2_faded = clip2.crossfadein(duration)
        return concatenate_videoclips([clip1_faded, clip2_faded], method="compose")
    except Exception as exc:
        print(f"Transition failed: {exc}. Concatenating without transition.")
        return concatenate_videoclips([clip1, clip2])


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
            processed_scenes.append((s_id, video_path, audio_path))

    return processed_scenes


def stitch_video(processed_scenes, storyboard):
    """Create final reel with captions and transitions using moviepy."""
    if not processed_scenes:
        print("❌ Error: No scenes were processed successfully.")
        return

    scene_clips = []

    for s_id, v_path, a_path in processed_scenes:
        try:
            video_clip = VideoFileClip(v_path)
            # Load audio to maintain original soundtrack
            audio_clip = VideoFileClip(a_path).audio
            video_clip = video_clip.set_audio(audio_clip)

            # Get narration text from storyboard
            narration = next(
                (scene["narration_text"] for scene in storyboard.get("scenes", []) if scene["scene_id"] == s_id),
                "The universe is full of mysteries.",
            )

            # Add caption overlay
            captioned_clip = add_caption_to_clip(video_clip, narration)
            scene_clips.append(captioned_clip)
            print(f"Scene {s_id} processed with caption.")
        except Exception as exc:
            print(f"Scene clip processing failed for {s_id}: {exc}")

    if not scene_clips:
        print("❌ Error: No scene clips could be created.")
        return

    # Combine clips with transitions
    print("Applying transitions between scenes...")
    final_clip = scene_clips[0]
    for clip in scene_clips[1:]:
        final_clip = apply_scene_transition(final_clip, clip, duration=0.6)

    # Export final video
    final_output = "output/final_reel.mp4"
    print(f"Exporting final reel to {final_output}...")
    try:
        final_clip.write_videofile(
            final_output,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            bitrate="5000k",
            threads=2,
            logger=None,
            verbose=False,
        )
        print(f"🎉 FINAL REEL READY: {final_output}")
    except Exception as exc:
        print(f"❌ Error exporting final reel: {exc}")


def main():
    global storyboard
    print("Starting Autonomous Reel Production Engine...")
    storyboard = generate_storyboard("What happens at the edge of the observable universe?")
    scenes = build_assets(storyboard)
    stitch_video(scenes, storyboard)


if __name__ == "__main__":
    main()
