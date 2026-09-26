import os
import json
import random
import asyncio
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
    "deep space 4k", "black hole accretion", "spinning galaxy vertical", 
    "supernova explosion motion", "wormhole tunnel space", "neutron star cosmic"
]

used_video_ids = set()

def extract_json_from_text(text):
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
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
    
    # 1. Try Gemini First (using gemini-3.8-flash as suggested by error log)
    if client_gemini:
        try:
            print("Attempting with Gemini API (gemini-3.8-flash)...")
            response = client_gemini.models.generate_content(
                model="gemini-3.8-flash",
                contents=f"{system_prompt}\n\n{user_prompt}",
                config={"response_mime_type": "application/json"}
            )
            return json.loads(extract_json_from_text(response.text))
        except Exception as e:
            print(f"Gemini failed: {e}")

    # 2. Try OpenRouter Fallback Second
    if OPENROUTER_API_KEY:
        try:
            print("Attempting with OpenRouter fallback...")
            url = "[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "google/gemma-2-9b-it:free",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }
            res = requests.post(url, headers=headers, json=data, timeout=30)
            res_json = res.json()
            return json.loads(extract_json_from_text(res_json['choices'][0]['message']['content']))
        except Exception as e:
            print(f"OpenRouter failed: {e}")

    raise Exception("All AI models and fallbacks failed to generate content.")

async def generate_voiceover(text, output_file):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await communicate.save(output_file)

def fetch_pexels_video(keyword, output_file):
    global used_video_ids
    if not PEXELS_API_KEY:
        return False

    headers = {"Authorization": PEXELS_API_KEY}
    search_terms = [keyword] + random.sample(BACKUP_KEYWORDS, len(BACKUP_KEYWORDS))
    
    for term in search_terms:
        page = random.randint(1, 5)
        url = f"[https://api.pexels.com/videos/search?query=](https://api.pexels.com/videos/search?query=){term}&orientation=portrait&per_page=10&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                videos = res.json().get("videos", [])
                for video in videos:
                    v_id = video.get("id")
                    if v_id not in used_video_ids:
                        v_files = video.get("video_files", [])
                        hd_file = next((f for f in v_files if f.get("height", 0) >= 1280), v_files[0])
                        
                        print(f"Downloading Pexels clip (ID: {v_id}) for '{term}'...")
                        v_data = requests.get(hd_file.get("link"), timeout=30).content
                        with open(output_file, "wb") as f:
                            f.write(v_data)
                        used_video_ids.add(v_id)
                        return True
        except Exception as e:
            print(f"Fetch error: {e}")
    return False

def build_assets(storyboard):
    os.makedirs("output/videos", exist_ok=True)
    os.makedirs("output/audio", exist_ok=True)
    processed_scenes = []
    
    for scene in storyboard.get("scenes", []):
        s_id = scene["scene_id"]
        narration = scene["narration_text"]
        keyword = scene.get("search_keyword", "space galaxy")
        
        audio_path = f"output/audio/scene_{s_id}.mp3"
        asyncio.run(generate_voiceover(narration, audio_path))
        
        video_path = f"output/videos/scene_{s_id}.mp4"
        if fetch_pexels_video(keyword, video_path):
            processed_scenes.append((s_id, video_path, audio_path))
            
    return processed_scenes

def stitch_video(processed_scenes):
    scene_outputs = []
    for s_id, v_path, a_path in processed_scenes:
        merged_path = f"output/videos/merged_{s_id}.mp4"
        cmd = [
            "ffmpeg", "-y", "-stream_loop", "-1",
            "-i", v_path, "-i", a_path,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-shortest", merged_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        scene_outputs.append(merged_path)
        
    concat_list = "output/concat_list.txt"
    with open(concat_list, "w") as f:
        for p in scene_outputs:
            f.write(f"file '{os.path.abspath(p)}'\n")
            
    final_output = "output/final_reel.mp4"
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", final_output
    ]
    subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"🎉 FINAL REEL READY: {final_output}")

def main():
    print("Starting Autonomous Reel Production Engine...")
    storyboard = generate_storyboard("What happens at the edge of the observable universe?")
    scenes = build_assets(storyboard)
    if scenes:
        stitch_video(scenes)
    else:
        print("❌ Error: No scenes were processed successfully.")

if __name__ == "__main__":
    main()
