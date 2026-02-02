from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from yt_dlp import YoutubeDL
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="YT Stream API (Safe, No Login Required)")

# CORS許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/stream/{video_id}")
def stream(video_id: str, quality: str = "best"):
    """
    安全版: ログイン不要動画限定
    video_id: YouTube動画ID
    quality: 'best'または'360p','720p'など
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'format': 'bestaudio/best' if quality == "best" else quality,
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
        'age_limit': None,
        'nocheckcertificate': True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Video not found or restricted: {e}")

    formats = info.get("formats", [])
    if not formats:
        raise HTTPException(status_code=503, detail="No stream formats found")

    # 日本語音声優先
    for f in formats:
        f_url = f.get("url")
        if not f_url:
            continue
        lang = (f.get("language") or "").lower()
        audio_track = str(f.get("audioTrack") or "").lower()
        if "ja" in lang or "japanese" in audio_track:
            return RedirectResponse(f_url)

    # fallback: ベストURL
    return RedirectResponse(formats[0]["url"])
