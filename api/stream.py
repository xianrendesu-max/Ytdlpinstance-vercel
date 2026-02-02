from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from yt_dlp import YoutubeDL
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="YT Stream API")

# CORS許可（フロントからのアクセス用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/stream/{video_id}")
def stream(video_id: str, quality: str = "best"):
    """
    video_id: YouTube動画ID
    quality: 'best'または'360p', '720p'など
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'format': 'bestaudio/best' if quality == "best" else quality,
        'quiet': True,
        'skip_download': True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Video not found: {e}")

    # フィルタして日本語優先も可能
    formats = info.get("formats", [])
    for f in formats:
        if f.get("url"):
            # 日本語音声優先の簡易チェック
            lang = (f.get("language") or "").lower()
            audio_track = str(f.get("audioTrack") or "").lower()
            if "en" in lang or "english" in audio_track:
                continue
            return RedirectResponse(f["url"])

    # 条件に合わなければベストURL
    if formats:
        return RedirectResponse(formats[0]["url"])

    raise HTTPException(status_code=503, detail="Stream unavailable")
