import os
import random
import shutil
import time
import logging
import pickle
import openai
import requests
import codecs
import concurrent.futures
import numpy as np
from PIL import Image
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    concatenate_videoclips,
    CompositeAudioClip
)
from moviepy.video.fx.fadein import fadein
from moviepy.video.fx.fadeout import fadeout
from moviepy.audio.fx.all import audio_loop
import textwrap
from moviepy.config import change_settings

# ============================ Coqui TTS Import ============================
from TTS.api import TTS  # Main class for generating speech

# ============================ Google API Imports ============================
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ------------------ Monkey-patch for Pillow 10+ ------------------
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

# ============================ Configuration ============================
# Locate ImageMagick automatically. Order: IMAGEMAGICK_BINARY env var → PATH → common
# Windows install location. This avoids the previous hardcoded version-specific path that
# broke on any machine without that exact ImageMagick build installed.
_im_path = (
    os.getenv("IMAGEMAGICK_BINARY")
    or shutil.which("magick")
    or r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
)
if os.path.exists(_im_path):
    change_settings({"IMAGEMAGICK_BINARY": _im_path})

LOG_FILE = 'youtube_shorts_automation.log'

class UTF8StreamHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream)
        self.stream = codecs.getwriter("utf-8")(self.stream.buffer)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        UTF8StreamHandler()
    ]
)

from dotenv import load_dotenv
load_dotenv()

if not os.path.exists(_im_path):
    logging.warning(
        "ImageMagick not found (looked for %s). Text captions/watermarks will fail until "
        "it is installed or IMAGEMAGICK_BINARY is set.", _im_path
    )

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

if not OPENAI_API_KEY:
    logging.error("OpenAI API key not set.")
    exit(1)
openai.api_key = OPENAI_API_KEY

if not PEXELS_API_KEY:
    logging.error("Pexels API key not set.")
    exit(1)

if not PIXABAY_API_KEY:
    logging.error("Pixabay API key not set.")
    exit(1)

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

OUTPUT_FOLDER = 'output_videos/'
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ============================ Tunable render settings (env-configurable) ============================
def _parse_resolution(value, default=(720, 1280)):
    try:
        w, h = value.lower().split('x')
        return (int(w), int(h))
    except Exception:
        return default

TARGET_RESOLUTION = _parse_resolution(os.getenv("SHORTS_RESOLUTION", "720x1280"))
VIDEO_FPS = int(os.getenv("SHORTS_FPS", "60"))
MUSIC_VOLUME = float(os.getenv("SHORTS_MUSIC_VOLUME", "0.08"))
CAPTION_FONTSIZE = int(os.getenv("SHORTS_CAPTION_FONTSIZE", "50"))


def with_retries(fn, *args, attempts=3, base_delay=2, label="operation", **kwargs):
    """Call fn with exponential-backoff retries on transient failures."""
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if i == attempts:
                logging.error(f"{label} failed after {attempts} attempts: {e}")
                raise
            wait = base_delay * (2 ** (i - 1))
            logging.warning(f"{label} attempt {i}/{attempts} failed: {e}; retrying in {wait}s")
            time.sleep(wait)


def chat_completion(**kwargs):
    """OpenAI chat call with retries so a transient API hiccup doesn't waste a whole video."""
    return with_retries(lambda: openai.ChatCompletion.create(**kwargs),
                        attempts=3, label="OpenAI chat")

# ============================ Categories and Static Trending Hashtags ============================
CATEGORIES = [
    "Mystery", "horror Story telling", "history of Game", "informative", "science",
    "interesting people", "trending news", "finance tips",
    "interesting facts", "psychology", "horror stories",
    "space exploration", "Cars", "history mysteries", "Money",
    "True Crime", "Tech Trends", "Motivational", "Self-Improvement",
    "History in a Nutshell", "Curiosities", "Fun Facts"
]

TRENDING_HASHTAGS = [
    "#YouTubeShortsChallenge", "#shorts", "#trending", "#viral",
    "#explore", "#foryou", "#YouTubeShorts", "#entertainment",
    "#fun", "#latest", "#discover", "#TechTrends", "#FunFacts",
    "#SelfImprovement", "#MindBlown", "#TrueCrime",
    "#UnsolvedMysteries", "#CrimeDocumentary",
    "#MysteryStories", "#ColdCases", "#StrangeFacts",
    "#DarkHistory", "#ConspiracyTheories", "#CrimeStories",
    "#MysteryUnveiled", "#GadgetReviews", "#LatestTechnology",
    "#TechNews", "#FutureTech", "#AIUpdates", "#TechTips",
    "#TechReviews", "#DigitalWorld", "#Innovation",
    "#Motivation", "#SuccessMindset", "#LifeHacks",
    "#ProductivityTips", "#PositiveThinking", "#DailyMotivation",
    "#PersonalGrowth", "#MindsetMatters", "#Inspiration",
    "#HistoryFacts", "#DidYouKnow", "#HistoricalEvents",
    "#HistoryUncovered", "#PastAndPresent", "#WorldHistory",
    "#AncientCivilizations", "#HistoryBuff", "#FamousFigures",
    "#TimelineTrivia", "#RandomFacts", "#WeirdButTrue",
    "#AmazingWorld", "#KnowledgeIsPower", "#FactsDaily",
    "#TriviaTime"
]

# ============================ Authentication ============================
def authenticate_youtube():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=8080)
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        logging.error(f"Authentication error: {e}")
        raise

# ============================ Hashtag Generation ============================
def generate_hashtags(category, min_count=5):
    """
    Ask ChatGPT for trending and relevant hashtags for the given category.
    Returns a list of at least min_count hashtags.
    """
    try:
        prompt = (
            f"Provide a list of at least {min_count} trending and relevant hashtags for a YouTube Short about {category}. "
            "Ensure that the hashtags are correct, popular, and will help get more views. "
            "Return the hashtags in a comma separated format."
        )
        response = chat_completion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.8
        )
        if 'choices' in response and len(response['choices']) > 0:
            hashtags_text = response['choices'][0]['message']['content'].strip()
            # Try splitting by comma first; if not, split by whitespace.
            if ',' in hashtags_text:
                hashtags = [tag.strip() for tag in hashtags_text.split(',') if tag.strip().startswith('#')]
            else:
                hashtags = [tag.strip() for tag in hashtags_text.split() if tag.strip().startswith('#')]
            if len(hashtags) < min_count:
                fallback = [tag for tag in TRENDING_HASHTAGS if tag not in hashtags]
                hashtags.extend(fallback[:(min_count - len(hashtags))])
            return hashtags[:min_count]
        else:
            logging.error("No valid hashtags generated by GPT.")
            return random.sample(TRENDING_HASHTAGS, min_count)
    except Exception as e:
        logging.error(f"Error generating hashtags: {e}")
        return random.sample(TRENDING_HASHTAGS, min_count)

# ============================ Content Generation ============================
def get_trending_topic():
    if random.random() < 0.5:
        return random.choice(CATEGORIES)
    else:
        return " ".join(random.sample(CATEGORIES, 2))

def generate_content_idea():
    if random.random() < 0.5:
        return random.choice(CATEGORIES)
    else:
        return get_trending_topic()

def generate_text_content(category, length=150):
    try:
        prompt = (
            f"Create a {length}-word YouTube Shorts script about '{category}'.\n"
            "1. Begin with a surprising question or statement to hook the viewer.\n"
            "2. Present 1-2 fun or interesting facts using simple language.\n"
            "3. Keep it exciting and understandable for a wide audience.\n"
            "4. End with a clear call-to-action to like, share, and subscribe.\n"
            "5. Make sure it can be spoken comfortably in under 20 seconds."
        )
        response = chat_completion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(length * 2),
            temperature=0.9
        )
        if 'choices' in response and len(response['choices']) > 0:
            return response['choices'][0]['message']['content'].strip()
        else:
            logging.error("No valid choices found in the GPT response.")
            return "Default script content. (placeholder)"
    except Exception as e:
        logging.error(f"Error generating script: {e}")
        return "Default script content. (placeholder)"
def generate_title(category):
    try:
        prompt = (
            f"Generate a catchy YouTube Short title for a video about {category}. "
            "Start with an attention-grabbing word and include at least one keyword from the category."
        )
        response = chat_completion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0.8
        )
        
        logging.info(f"Raw title response: {response}")
        
        title_part = ""
        if 'choices' in response and len(response['choices']) > 0:
            title_part = response['choices'][0]['message']['content'].strip()
        
        # Remove unwanted characters
        for ch in ["'", "’", "‘", '"', "“", "”"]:
            title_part = title_part.replace(ch, "")
        
        # Fallback if title is empty
        if not title_part:
            title_part = f"{category.capitalize()} #shorts #trending"
        
        # Generate hashtags (at least 5)
        hashtags = generate_hashtags(category, min_count=5)
        hashtags_str = " ".join(hashtags)
        
        # Build final title and enforce YouTube's max length of 100 characters.
        final_title = f"{title_part} {hashtags_str}"
        if len(final_title) > 100:
            # Reserve space for hashtags and a space between
            allowed_title_length = 100 - len(hashtags_str) - 1
            # Truncate the title part and remove any trailing spaces
            title_part = title_part[:allowed_title_length].rstrip()
            final_title = f"{title_part} {hashtags_str}"
        
        logging.info(f"Generated title: {final_title}")
        return final_title
    except Exception as e:
        logging.error(f"Error generating title: {e}")
        fallback_title = f"{category.capitalize()} #shorts #trending"
        for ch in ["'", "’", "‘", '"', "“", "”"]:
            fallback_title = fallback_title.replace(ch, "")
        hashtags = generate_hashtags(category, min_count=5)
        fallback_title += " " + " ".join(hashtags)
        # Ensure fallback title also meets the length requirement
        if len(fallback_title) > 100:
            allowed_title_length = 100 - len(" ".join(hashtags)) - 1
            fallback_title = fallback_title[:allowed_title_length].rstrip() + " " + " ".join(hashtags)
        return fallback_title



def generate_description(category):
    try:
        prompt = (
            f"Write an engaging YouTube Short description for a video about {category}. "
            "Include 2-3 bullet points summarizing the key info, and ask viewers to like, share, and subscribe."
        )
        response = chat_completion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.7
        )
        if 'choices' in response and len(response['choices']) > 0:
            description = response['choices'][0]['message']['content'].strip()
            hashtags = generate_hashtags(category, min_count=5)
            description += "\n\n" + " ".join(hashtags)
            logging.info(f"Generated description: {description}")
            return description
        else:
            logging.error("No valid choices found in the GPT response for the description.")
            fallback_description = (
                f"Discover amazing facts about {category}! Don't forget to like, share, and subscribe.\n\n"
            )
            hashtags = generate_hashtags(category, min_count=5)
            fallback_description += " ".join(hashtags)
            return fallback_description
    except Exception as e:
        logging.error(f"Error generating description: {e}")
        fallback_description = (
            f"Discover amazing facts about {category}! Don't forget to like, share, and subscribe.\n\n"
        )
        hashtags = generate_hashtags(category, min_count=5)
        fallback_description += " ".join(hashtags)
        return fallback_description

# ============================ Voiceover Generation ============================
def generate_voiceover(text, output_path):
    try:
        voice_models = [
            "tts_models/en/ljspeech/tacotron2-DDC",
            "tts_models/en/ljspeech/tacotron2-DDC_ph"
        ]
        random_model = random.choice(voice_models)
        tts = TTS(model_name=random_model)
        wav_output = output_path.replace(".mp3", ".wav")
        tts.tts_to_file(text=text, file_path=wav_output)
        logging.info(f"Voiceover saved to {wav_output} using model: {random_model}")
        return wav_output
    except Exception as e:
        logging.error(f"Error generating voiceover with Coqui TTS: {e}")
        raise

# ============================ Video Processing ============================
def split_script_into_segments(script, words_per_segment=6):
    words = script.split()
    length = len(words)
    if length > 120:
        words_per_segment = 8
    elif length < 60:
        words_per_segment = 5
    segments = [' '.join(words[i:i + words_per_segment]) for i in range(0, len(words), words_per_segment)]
    return segments

def add_animated_captions(video_clip, script, duration):
    segments = split_script_into_segments(script)
    num_segments = len(segments)
    if num_segments == 0:
        return video_clip
    segment_duration = duration / num_segments
    caption_clips = []
    for idx, segment in enumerate(segments):
        start_time = idx * segment_duration
        txt_clip = TextClip(
            segment,
            fontsize=CAPTION_FONTSIZE,
            color='white',
            stroke_color='black',
            stroke_width=2,
            font='Arial-Bold',
            method='caption',
            size=(int(video_clip.w * 0.8), None),
            align='center'
        ).set_start(start_time).set_duration(segment_duration)
        txt_clip = txt_clip.set_position(
            lambda t, st=start_time: (
                'center', 
                video_clip.h / 2 + 20 * np.sin((t - st) * 3)
            )
        )
        txt_clip = txt_clip.fadein(0.3).fadeout(0.3)
        caption_clips.append(txt_clip)
    return CompositeVideoClip([video_clip] + caption_clips)

def add_brand_watermark(video_clip):
    watermark_text = "PurffleStudios"
    txt_clip = (
        TextClip(
            watermark_text,
            fontsize=32,
            color='white',
            stroke_color='black',
            stroke_width=3,
            font='Arial-Bold'
        )
        .set_position(('right', 'top'))
        .set_duration(video_clip.duration)
        .margin(right=20, top=20, opacity=0)
    )
    return CompositeVideoClip([video_clip, txt_clip])

def add_end_screen_cta(video_clip):
    end_duration = 3
    start_time = video_clip.duration - end_duration
    cta_text = "Like, Share & Subscribe!"
    txt_clip = (
        TextClip(
            cta_text,
            fontsize=60,
            color='yellow',
            stroke_color='black',
            stroke_width=2,
            font='Arial-Bold'
        )
        .set_position('center')
        .set_start(start_time)
        .set_duration(end_duration)
        .fadein(0.5)
        .fadeout(0.5)
    )
    return CompositeVideoClip([video_clip, txt_clip])

def resize_video(video_path, target_resolution=None):
    target_resolution = target_resolution or TARGET_RESOLUTION
    try:
        clip = VideoFileClip(video_path)
        resized_clip = clip.resize(newsize=target_resolution)
        resized_path = video_path.replace(".mp4", "_resized.mp4")
        resized_clip.write_videofile(
            resized_path,
            codec="libx264",
            audio_codec="aac",
            fps=VIDEO_FPS,
            ffmpeg_params=['-threads', '0']
        )
        clip.close()
        resized_clip.close()
        return resized_path
    except Exception as e:
        logging.error(f"Error resizing video {video_path}: {e}")
        return video_path

def download_video(video_url, video_path):
    def _do():
        response = requests.get(video_url, stream=True, timeout=30)
        response.raise_for_status()
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return video_path
    try:
        path = with_retries(_do, attempts=3, label=f"download {os.path.basename(video_path)}")
        logging.info(f"Downloaded video to {path}")
        return path
    except Exception:
        return None

# ============================ Fetch Videos from Pexels & Pixabay ============================
def fetch_pexels_videos(query, num_videos=3):
    try:
        expanded_query = f"{query} concept OR {query} background"
        headers = {"Authorization": PEXELS_API_KEY}
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(expanded_query)}&per_page=10"
        response = requests.get(url, headers=headers)
        data = response.json()
        video_paths = []
        if "videos" in data and len(data["videos"]) > 0:
            selected_videos = data["videos"][:num_videos]
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                for video in selected_videos:
                    video_files = video.get("video_files", [])
                    if not video_files:
                        continue
                    video_files.sort(key=lambda x: x['width'] * x['height'], reverse=True)
                    selected_video = video_files[0]
                    video_url = selected_video['link']
                    local_path = os.path.join(
                        OUTPUT_FOLDER,
                        f"pexels_background_{query.replace(' ', '_')}_{random.randint(1000,9999)}.mp4"
                    )
                    futures.append(executor.submit(download_video, video_url, local_path))
                for future in concurrent.futures.as_completed(futures):
                    path = future.result()
                    if path:
                        video_paths.append(path)
        return video_paths
    except Exception as e:
        logging.error(f"Error fetching videos from Pexels for query '{query}': {e}")
        return []

def fetch_pixabay_videos(query, num_videos=3):
    try:
        expanded_query = f"{query} background OR {query} concept"
        url = (
            f"https://pixabay.com/api/videos/"
            f"?key={PIXABAY_API_KEY}"
            f"&q={requests.utils.quote(expanded_query)}"
            f"&per_page=10"
        )
        response = requests.get(url)
        data = response.json()
        video_paths = []
        if "hits" in data and len(data["hits"]) > 0:
            selected_videos = data["hits"][:num_videos]
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                for video in selected_videos:
                    video_files = video.get("videos", {})
                    quality_order = ['large', 'medium', 'small']
                    selected_video = None
                    for quality in quality_order:
                        if quality in video_files:
                            selected_video = video_files[quality]
                            break
                    if not selected_video:
                        continue
                    video_url = selected_video['url']
                    local_path = os.path.join(
                        OUTPUT_FOLDER,
                        f"pixabay_background_{query.replace(' ', '_')}_{random.randint(1000,9999)}.mp4"
                    )
                    futures.append(executor.submit(download_video, video_url, local_path))
                for future in concurrent.futures.as_completed(futures):
                    path = future.result()
                    if path:
                        video_paths.append(path)
        return video_paths
    except Exception as e:
        logging.error(f"Error fetching videos from Pixabay for query '{query}': {e}")
        return []

# ============================ Additional Video Editing Functions ============================
def add_background_music(video_clip, music_path):
    try:
        if not os.path.exists(music_path):
            logging.info(f"No background music found at {music_path}. Skipping.")
            return video_clip
        music_clip = AudioFileClip(music_path)
        video_duration = video_clip.duration
        music_duration = music_clip.duration
        if music_duration < video_duration:
            music_clip = audio_loop(music_clip, duration=video_duration)
        else:
            music_clip = music_clip.subclip(0, video_duration)
        final_music_clip = music_clip.volumex(MUSIC_VOLUME)
        final_audio = CompositeAudioClip([video_clip.audio, final_music_clip])
        final_clip = video_clip.set_audio(final_audio)
        return final_clip
    except Exception as e:
        logging.error(f"Error adding background music from {music_path}: {e}")
        return video_clip

def add_channel_intro(main_clip_path):
    intro_path = "channel_intro.mp4"  # Replace with your actual intro path if available
    if not os.path.exists(intro_path):
        logging.info("Intro clip not found, skipping channel intro.")
        return VideoFileClip(main_clip_path)
    try:
        intro_clip = VideoFileClip(intro_path).fx(fadein, 0.5).fx(fadeout, 0.5)
        main_clip = VideoFileClip(main_clip_path)
        final_clip = concatenate_videoclips([intro_clip, main_clip], method="compose")
        combined_path = main_clip_path.replace(".mp4", "_with_intro.mp4")
        final_clip.write_videofile(
            combined_path,
            codec="libx264",
            audio_codec="aac",
            fps=VIDEO_FPS,
            ffmpeg_params=['-threads', '0']
        )
        intro_clip.close()
        main_clip.close()
        final_clip.close()
        return VideoFileClip(combined_path)
    except Exception as e:
        logging.error(f"Error adding channel intro: {e}")
        return VideoFileClip(main_clip_path)

def create_video(script, pexels_background_paths, pixabay_background_paths, output_path, voiceover_path):
    try:
        voiceover_wav_path = generate_voiceover(script, voiceover_path)
        audio_clip = AudioFileClip(voiceover_wav_path)
        voiceover_duration = audio_clip.duration
        all_background_paths = pexels_background_paths + pixabay_background_paths
        resized_clips = []
        for idx, path in enumerate(all_background_paths):
            rclip = VideoFileClip(resize_video(path))
            if idx == 0:
                rclip = rclip.fx(fadein, 0.5)
            rclip = rclip.fx(fadeout, 0.5)
            resized_clips.append(rclip)
        if len(resized_clips) > 1:
            concatenated_clip = concatenate_videoclips(resized_clips, method="compose")
        elif len(resized_clips) == 1:
            concatenated_clip = resized_clips[0]
        else:
            logging.error("No background clips available to concatenate.")
            return None
        if concatenated_clip.duration < voiceover_duration:
            n_loops = int(voiceover_duration // concatenated_clip.duration) + 1
            concatenated_clip = concatenate_videoclips([concatenated_clip] * n_loops, method="compose")
        final_clip = concatenated_clip.subclip(0, voiceover_duration).set_audio(audio_clip)
        final_clip = add_animated_captions(final_clip, script, voiceover_duration)
        temp_path = output_path.replace(".mp4", "_temp.mp4")
        final_clip.write_videofile(
            temp_path,
            codec="libx264",
            audio_codec="aac",
            fps=VIDEO_FPS,
            ffmpeg_params=['-threads', '0']
        )
        final_clip.close()
        final_clip = add_channel_intro(temp_path)
        final_clip = add_brand_watermark(final_clip)
        final_clip = add_end_screen_cta(final_clip)
        music_path = "back.mp3"
        if os.path.exists(music_path):
            final_clip = add_background_music(final_clip, music_path)
        else:
            logging.info(f"Background music file '{music_path}' not found. Skipping.")
        final_clip.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=VIDEO_FPS,
            ffmpeg_params=['-threads', '0']
        )
        final_clip.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return output_path
    except Exception as e:
        logging.error(f"Error creating video: {e}")
        return None

# ============================ YouTube Upload ============================
def upload_video_to_youtube(youtube, video_path, title, description, tags, category_id="22"):
    try:
        if 'shorts' not in tags:
            tags.append('shorts')
        request_body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": "public"
            }
        }
        media = MediaFileUpload(video_path, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=request_body,
            media_body=media
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logging.info(f"Upload progress: {int(status.progress() * 100)}%")
        return response
    except Exception as e:
        logging.error(f"Error uploading video: {e}")
        return None

# ============================ Processing Shorts ============================
def process_single_short(index, upload=True):
    """Create one Short. Returns True on success. When upload=False (dry-run) the
    generated MP4 is kept on disk for inspection instead of being uploaded + deleted."""
    try:
        category = generate_content_idea()
        script = generate_text_content(category, length=150)
        title = generate_title(category)
        description = generate_description(category)
        pexels_background_paths = fetch_pexels_videos(category, num_videos=3)
        pixabay_background_paths = fetch_pixabay_videos(category, num_videos=3)
        if not pexels_background_paths and not pixabay_background_paths:
            logging.error("No suitable background videos found on Pexels or Pixabay, skipping.")
            return False
        timestamp = int(time.time())
        video_file = os.path.join(
            OUTPUT_FOLDER,
            f"{category.replace(' ', '_')}_{timestamp}.mp4"
        )
        voiceover_file = os.path.join(
            OUTPUT_FOLDER,
            f"voiceover_{category.replace(' ', '_')}_{timestamp}.mp3"
        )
        logging.info(f"Creating video {index} for category: {category}")
        video_path = create_video(script, pexels_background_paths, pixabay_background_paths, video_file, voiceover_file)
        if not video_path:
            logging.error("Failed to create video.")
            return False

        if not upload:
            logging.info(f"[dry-run] Video kept at: {video_file} (skipped upload + cleanup)\n")
            return True

        tags = [
            "shorts", "trending", category, "viral", "entertainment",
            "subscribe", "facts", "amazing"
        ]
        logging.info(f"Uploading video: {video_file}")
        # Authenticate separately for each thread to avoid sharing issues
        youtube = authenticate_youtube()
        upload_response = upload_video_to_youtube(youtube, video_file, title, description, tags)
        ok = bool(upload_response)
        if ok:
            video_url = f"https://www.youtube.com/watch?v={upload_response['id']}"
            logging.info(f"Uploaded successfully: {video_url}\n")
        else:
            logging.error(f"Failed to upload video: {video_file}")
        try:
            os.remove(video_file)
            if os.path.exists(voiceover_file.replace(".mp3", ".wav")):
                os.remove(voiceover_file.replace(".mp3", ".wav"))
            for path in pexels_background_paths + pixabay_background_paths:
                if os.path.exists(path):
                    os.remove(path)
            logging.info(f"Cleaned up files for video: {video_file}")
        except Exception as cleanup_error:
            logging.error(f"Error cleaning up files: {cleanup_error}")
        return ok
    except Exception as e:
        logging.error(f"Error processing short {index}: {e}")
        return False

# ============================ Automation Loop ============================
def automate_youtube_shorts(batch_size=5, batch_delay=5, once=False, upload=True, max_videos=None):
    batch_num = 0
    total_ok = 0
    try:
        while True:
            batch_num += 1
            this_batch = batch_size
            if max_videos is not None:
                remaining = max_videos - total_ok
                if remaining <= 0:
                    break
                this_batch = min(batch_size, remaining)
            start_time = time.time()
            logging.info(f"Starting batch {batch_num} of {this_batch} shorts "
                         f"({'UPLOAD' if upload else 'DRY-RUN'}).")
            with concurrent.futures.ThreadPoolExecutor(max_workers=this_batch) as executor:
                futures = [executor.submit(process_single_short, i, upload)
                           for i in range(1, this_batch + 1)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]
            ok = sum(1 for r in results if r)
            total_ok += ok
            elapsed_time = time.time() - start_time
            logging.info(f"Batch {batch_num} done in {elapsed_time:.1f}s — "
                         f"{ok}/{this_batch} succeeded, {this_batch - ok} failed "
                         f"(total produced: {total_ok}).")
            if once:
                logging.info("Single-batch mode (--once) complete; exiting.")
                break
            if max_videos is not None:
                if ok == 0:
                    logging.warning("No videos produced this batch; stopping to avoid a loop.")
                    break
                if total_ok >= max_videos:
                    logging.info(f"Reached target of {max_videos} videos; exiting.")
                    break
            # Wait between batches (configurable via SHORTS_BATCH_DELAY).
            time.sleep(batch_delay)
    except KeyboardInterrupt:
        logging.info("Automation stopped by user.")
    except Exception as e:
        logging.error(f"Automation failed: {e}")

# ============================ Main Execution ============================
if __name__ == "__main__":
    import sys
    # Flags:  --once       run a single batch then exit (great for testing)
    #         --no-upload  generate videos but skip YouTube upload (keeps the MP4s)
    #         --count N    produce exactly N shorts, then stop
    once = "--once" in sys.argv
    do_upload = "--no-upload" not in sys.argv
    max_videos = None
    if "--count" in sys.argv:
        idx = sys.argv.index("--count")
        if idx + 1 < len(sys.argv):
            try:
                max_videos = max(1, int(sys.argv[idx + 1]))
            except ValueError:
                logging.warning("--count needs a number, e.g. --count 3; ignoring.")
    # Number of Shorts per batch and the pause between batches are env-configurable.
    automate_youtube_shorts(
        batch_size=int(os.getenv("SHORTS_BATCH_SIZE", "5")),
        batch_delay=int(os.getenv("SHORTS_BATCH_DELAY", "5")),
        once=once,
        upload=do_upload,
        max_videos=max_videos,
    )
