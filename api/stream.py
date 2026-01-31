from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import yt_dlp
import tempfile
import os

app = FastAPI()

@app.get("/api/stream")
async def stream_video(url: str):
    """
    簡単なVercel向けMP4ストリーミングAPI
    URLパラメータでYouTubeなどの動画を取得してストリーム配信
    """
    # 一時ファイルに動画を保存
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp_path = tmp_file.name
    tmp_file.close()

    # yt-dlpで動画を取得
    ydl_opts = {
        "format": "best",
        "outtmpl": tmp_path,
        "quiet": True,  # ログ抑制
        "noplaylist": True  # プレイリストは無視
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return {"error": str(e)}

    # StreamingResponseで配信
    def iterfile():
        with open(tmp_path, "rb") as f:
            yield from f
        os.remove(tmp_path)  # 配信後に削除

    return StreamingResponse(iterfile(), media_type="video/mp4")
