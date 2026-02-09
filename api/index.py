from fastapi import FastAPI, HTTPException
from yt_dlp import YoutubeDL
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# --- CORS設定 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- スレッドプール ---
executor = ThreadPoolExecutor()

# --- yt-dlp 基本設定 ---
ydl_opts_base = {
    "quiet": True,
    "skip_download": True,
    "nocheckcertificate": True,
    "format": "best",
    "proxy": "http://ytproxy-siawaseok.duckdns.org:3007"
}

ydl_opts_flat = {
    **ydl_opts_base,
    "extract_flat": "in_playlist",
    "playlist_items": "1-50",
    "lazy_playlist": True,
}

# --- キャッシュ & 処理中管理 ---
VIDEO_CACHE = {}      # { id: (timestamp, data, duration) }
PLAYLIST_CACHE = {}
CHANNEL_CACHE = {}
PROCESSING_IDS = set()

DEFAULT_CACHE_DURATION = 600    # 10分
LONG_CACHE_DURATION = 14200     # 約4時間
CHANNEL_CACHE_DURATION = 86400  # 24時間

# --- キャッシュ管理 ---
def cleanup_cache():
    """期限切れのキャッシュをクリーンアップ"""
    now = time.time()
    for cache in [VIDEO_CACHE, PLAYLIST_CACHE, CHANNEL_CACHE]:
        expired = [k for k, (ts, _, dur) in cache.items() if now - ts >= dur]
        for k in expired:
            del cache[k]

def get_cache(cache, key):
    """キャッシュ取得。期限切れならNone"""
    if key in cache:
        ts, data, dur = cache[key]
        if time.time() - ts < dur:
            return data
        del cache[key]
    return None

def set_cache(cache, key, data, duration):
    cache[key] = (time.time(), data, duration)

# --- システム・管理 API ---
@app.get("/status")
def get_status():
    """現在非同期処理中のID一覧を返す"""
    return {
        "processing_count": len(PROCESSING_IDS),
        "processing_ids": list(PROCESSING_IDS)
    }

@app.get("/api/2/cache")
def list_cache():
    """すべてのキャッシュ状況をカテゴリ別に表示"""
    now = time.time()
    def format_map(c):
        return {
            k: {
                "age_sec": int(now - v[0]),
                "remaining_sec": int(v[2] - (now - v[0])),
                "total_duration": v[2]
            } for k, v in c.items()
        }
    return {
        "video_streams": format_map(VIDEO_CACHE),
        "playlists": format_map(PLAYLIST_CACHE),
        "channels": format_map(CHANNEL_CACHE)
    }

@app.delete("/api/2/cache/{item_id}")
def delete_cache(item_id: str):
    """指定したIDのキャッシュを削除"""
    deleted = False
    for cache in [VIDEO_CACHE, PLAYLIST_CACHE, CHANNEL_CACHE]:
        if item_id in cache:
            del cache[item_id]
            deleted = True
    if deleted:
        return {"status": "success", "message": f"ID: {item_id} のキャッシュを削除しました。"}
    raise HTTPException(status_code=404, detail="キャッシュが存在しません。")

# --- 内部ヘルパー ---
async def run_in_executor(func):
    """スレッドプールで同期処理を非同期実行"""
    return await asyncio.to_thread(func)

def extract_formats(info, filter_mhtml=True):
    """動画情報からストリームフォーマットを抽出"""
    formats = []
    for f in info.get("formats", []):
        if f.get("url") and (not filter_mhtml or f.get("ext") != "mhtml"):
            formats.append({
                "itag": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution"),
                "url": f.get("url")
            })
    return formats

# --- メイン API ---
@app.get("/stream/{video_id}")
async def get_streams(video_id: str):
    cleanup_cache()
    cached = get_cache(VIDEO_CACHE, video_id)
    if cached: 
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    PROCESSING_IDS.add(video_id)
    try:
        def fetch():
            with YoutubeDL(ydl_opts_base) as ydl:
                return ydl.extract_info(url, download=False)

        info = await run_in_executor(fetch)
        formats = extract_formats(info)

        dur = LONG_CACHE_DURATION if len(formats) >= 12 else DEFAULT_CACHE_DURATION
        res = {"title": info.get("title"), "id": video_id, "formats": formats}
        set_cache(VIDEO_CACHE, video_id, res, dur)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        PROCESSING_IDS.discard(video_id)

@app.get("/m3u8/{video_id}")
async def get_m3u8(video_id: str):
    """iOS User-Agentを使用してHLS(m3u8)マニフェストURLを抽出"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    PROCESSING_IDS.add(video_id)
    try:
        def fetch():
            opts = {**ydl_opts_base,
                    "user_agent": "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)"}
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await run_in_executor(fetch)
        streams = [
            {
                "url": f.get("url"),
                "resolution": f.get("resolution"),
                "protocol": f.get("protocol"),
                "ext": f.get("ext")
            }
            for f in info.get("formats", [])
            if f.get("protocol") == "m3u8_native" or ".m3u8" in f.get("url", "")
        ]
        if not streams and info.get("hls_url"):
            streams.append({
                "url": info.get("hls_url"),
                "resolution": "adaptive",
                "protocol": "m3u8_native",
                "ext": "m3u8"
            })

        return {"title": info.get("title"), "video_id": video_id, "m3u8_streams": streams}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        PROCESSING_IDS.discard(video_id)

# --- プレイリスト API ---
@app.get("/playlist/{playlist_id}")
async def get_playlist(playlist_id: str):
    cleanup_cache()
    cached = get_cache(PLAYLIST_CACHE, playlist_id)
    if cached:
        return cached

    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    if playlist_id.startswith("RD"):
        url = f"https://www.youtube.com/watch?list={playlist_id}"

    PROCESSING_IDS.add(playlist_id)
    try:
        def fetch():
            with YoutubeDL(ydl_opts_flat) as ydl:
                return ydl.extract_info(url, download=False)

        info = await run_in_executor(fetch)
        entries = [
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "thumbnail": e.get("thumbnails", [{}])[-1].get("url") if e.get("thumbnails") else None
            } for e in info.get("entries", []) if e
        ]
        res = {"id": playlist_id, "title": info.get("title"), "video_count": len(entries), "entries": entries}
        set_cache(PLAYLIST_CACHE, playlist_id, res, LONG_CACHE_DURATION)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        PROCESSING_IDS.discard(playlist_id)

# --- チャンネル API ---
@app.get("/channel/{channel_id}")
async def get_channel(channel_id: str):
    cleanup_cache()
    cached = get_cache(CHANNEL_CACHE, channel_id)
    if cached:
        return cached

    url = f"https://www.youtube.com/{channel_id}/videos" if channel_id.startswith("@") else f"https://www.youtube.com/channel/{channel_id}/videos"
    PROCESSING_IDS.add(channel_id)
    try:
        def fetch():
            with YoutubeDL(ydl_opts_flat) as ydl:
                return ydl.extract_info(url, download=False)

        info = await run_in_executor(fetch)
        videos = [
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "view_count": e.get("view_count")
            } for e in info.get("entries", []) if e
        ]
        res = {"channel_id": info.get("id"), "name": info.get("uploader") or info.get("channel"), "videos": videos}
        set_cache(CHANNEL_CACHE, channel_id, res, CHANNEL_CACHE_DURATION)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        PROCESSING_IDS.discard(channel_id)
