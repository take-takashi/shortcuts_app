import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from av.error import FFmpegError

from AudioInfoExtractor import TeamAikoInfoExtractor, get_extractor
from AudioInfoExtractor.team_aiko import (
    normalize_publication_date,
    resolve_team_aiko_publish_date,
)
from AudioInfoExtractor.vimeo_audio import resolve_vimeo_audio
from MyFfmpegHelper.my_ffmpeg_helper import FfmpegMetadata, MyFfmpegHelper
from MyLoggerHelper.my_logger_helper import MyLoggerHelper
from MyPathHelper.my_path_helper import MyPathHelper


def read_safari_page() -> dict[str, str]:
    """ログイン済みの現在タブを取得する。HTMLやCookieはディスクへ保存しない。"""
    script = '''tell application "Safari"
        do JavaScript "JSON.stringify({url:location.href,html:document.documentElement.outerHTML})" in current tab of front window
    end tell'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script], check=True, capture_output=True,
            text=True, timeout=30,
        )
        page = json.loads(result.stdout)
        if (not isinstance(page, dict) or not isinstance(page.get("html"), str)
                or not isinstance(page.get("url"), str)
                or urlsplit(page["url"]).scheme not in ("http", "https")):
            raise ValueError
        return page
    except (OSError, subprocess.SubprocessError, ValueError):
        raise RuntimeError(
            "Safariの現在タブを取得できませんでした。対象ページを開き、"
            "Safariの開発メニューで「Apple EventsからのJavaScriptを許可」を有効にしてください。"
        ) from None


def _download_vimeo_audio(audio_info, download_dir, *, page_url, overwrite, logger):
    """Vimeoの音声のみを取得し、既存のMP3処理とは独立してM4Aに保存する。"""
    parts = [audio_info.program_name, audio_info.broadcast_date, audio_info.episode_title]
    filename = "_".join(MyPathHelper.sanitize_filepath(p) for p in parts if p) + ".m4a"
    destination = Path(download_dir) / filename
    if destination.exists() and not overwrite:
        raise FileExistsError(f"保存先が既に存在します（上書きには --overwrite）: {destination}")
    # ファイル名は既存のYYYYMMDD形式、表示タイトルと日付タグはYYYY-MM-DD形式にする。
    metadata: FfmpegMetadata = {
        "title": audio_info.episode_title, "artist": audio_info.artist_name,
        "album": audio_info.program_name,
    }
    if audio_info.broadcast_date:
        date = datetime.strptime(audio_info.broadcast_date, "%Y%m%d").date().isoformat()
        metadata["title"] = f"{date} {audio_info.episode_title}"
        metadata["date"] = date
        logger.info("公開日: %s / タイトル: %s", date, metadata["title"])
    logger.info("Vimeoの音声専用HLSを取得しています...")
    with requests.Session() as session, tempfile.TemporaryDirectory(prefix="shortcuts-vimeo-") as temporary:
        source = resolve_vimeo_audio(
            audio_info.audio_src, page_url or audio_info.referer, session=session,
        )
        cover_path = None
        if audio_info.cover_image_url:
            try:
                response = session.get(
                    audio_info.cover_image_url, headers={"Referer": source.referer}, timeout=30,
                )
                response.raise_for_status()
                cover_path = str(Path(temporary) / "cover")
                Path(cover_path).write_bytes(response.content)
            except requests.RequestException:
                logger.warning("カバー画像を取得できなかったため、音声とタグのみ保存します。")
                cover_path = None
        MyFfmpegHelper.save_aac_as_m4a(
            input_path=source.url, output_path=str(destination),
            metadata=metadata,
            referer=source.referer, cover_path=cover_path,
            expected_duration=source.duration, overwrite=overwrite, logger=logger,
        )
    logger.info("保存しました: %s", destination)


# --- HTMLファイル入力は従来の呼び出し方を維持する ---
def download_audio_from_html(
    html_path, domain, download_dir, *, logger, page_url="", overwrite=False, broadcast_date="",
):
    """HTMLファイルから音声を保存する。成功時はTrue、失敗時はFalse。"""
    try:
        html_content = Path(html_path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("HTMLファイルを読み込めませんでした: %s", exc)
        return False
    return download_audio_content(
        html_content, domain, download_dir, logger=logger, page_url=page_url,
        overwrite=overwrite, broadcast_date=broadcast_date,
    )


def download_audio_content(
    html_content, domain, download_dir, *, logger, page_url="", overwrite=False, broadcast_date="",
):
    """HTML文字列を解析し、サイトの配信方式に応じて音声を保存する。"""
    logger.info("ドメイン: %s", domain)
    logger.info("ダウンロード先ディレクトリ: %s", download_dir)
    try:
        os.makedirs(download_dir, exist_ok=True)
        # ドメインに基づいて適切なExtractorを取得
        extractor = get_extractor(domain, logger=logger)
        if not extractor:
            logger.warning(f"未対応のドメインです: {domain}")
            return False

        # 音声情報を取得
        audio_info_list = extractor.get_audio_info(html_content)

        if not audio_info_list:
            logger.error("音声情報の取得に失敗しました。")
            return False

        for audio_info in audio_info_list:
            if isinstance(extractor, TeamAikoInfoExtractor):
                # アップロード日や実行日ではなく、サイトの公開日を配信日として使う。
                if broadcast_date:
                    audio_info.broadcast_date = normalize_publication_date(broadcast_date)
                else:
                    audio_info.broadcast_date = resolve_team_aiko_publish_date(
                        html_content, audio_info.episode_title, page_url=page_url,
                    )
            if audio_info.source_type == "vimeo":
                _download_vimeo_audio(
                    audio_info, download_dir, page_url=page_url, overwrite=overwrite, logger=logger,
                )
                continue
            # --- 既存サイトの直接配信MP3処理は維持する ---
            sanitized_program = MyPathHelper.sanitize_filepath(audio_info.program_name)
            sanitized_episode = MyPathHelper.sanitize_filepath(audio_info.episode_title)
            temp_filename = "temp_audio.mp3"
            if audio_info.broadcast_date:
                final_filename = (
                    f"{sanitized_program}_{audio_info.broadcast_date}_{sanitized_episode}.mp3"
                )
            else:
                final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
            temp_filepath = os.path.join(download_dir, temp_filename)
            final_filepath = os.path.join(download_dir, final_filename)

            logger.info(
                f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}"
            )
            response = requests.get(audio_info.audio_src, stream=True)
            response.raise_for_status()
            with open(temp_filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("ダウンロードが完了しました。")

            # --- ffmpeg処理 ---
            metadata: FfmpegMetadata = {
                "title": audio_info.episode_title,
                "artist": audio_info.artist_name,
                "album": audio_info.program_name,
            }

            temp_cover_path = None
            if audio_info.cover_image_url:
                temp_cover_path = os.path.join(download_dir, "temp_cover.jpg")
                logger.info(f"カバー画像をダウンロードしています: {temp_cover_path}")
                cover_res = requests.get(audio_info.cover_image_url)
                with open(temp_cover_path, "wb") as f:
                    f.write(cover_res.content)

            MyFfmpegHelper.embed_metadata(
                input_path=temp_filepath,
                output_path=final_filepath,
                metadata=metadata,
                cover_path=temp_cover_path,
                logger=logger,
            )

            # 一時ファイルを削除
            if temp_cover_path and os.path.exists(temp_cover_path):
                os.remove(temp_cover_path)
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)

            logger.info(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")
        return True
    except FFmpegError:
        # PyAVの例外に含まれる署名付きURLは出力しない。
        logger.error("PyAVによる音声取得・保存に失敗しました。ページを開き直して再試行してください。")
        return False
    except Exception as e:
        logger.error("音声の保存に失敗しました: %s", e)
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="HTMLファイルまたはSafariの現在タブから音声を保存します。"
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--html", help="対象のHTMLファイルのパス")
    inputs.add_argument("--safari", action="store_true", help="Safariで開いている現在タブを取得")
    parser.add_argument("--domain", help="HTMLの取得元ドメイン（--html使用時は必須）")
    parser.add_argument("--page-url", default="", help="元ページのURL（VimeoへのReferer）")
    parser.add_argument("--download_dir", default=".", help="ダウンロード先ディレクトリ")
    parser.add_argument("--overwrite", action="store_true", help="既存のVimeo音声ファイルを上書き")
    parser.add_argument(
        "--broadcast-date", type=normalize_publication_date,
        help="Team aikoの公開日を手動指定（YYYY-MM-DD）。省略時は一覧から取得",
    )
    args = parser.parse_args(argv)
    if args.html and not args.domain:
        parser.error("--htmlには--domainを指定してください。")

    try:
        download_directory = MyPathHelper.replace_safe_path(args.download_dir)
        os.makedirs(download_directory, exist_ok=True)
        logger = MyLoggerHelper.setup_logger(__name__, download_directory)
        options = {
            "logger": logger, "page_url": args.page_url, "overwrite": args.overwrite,
            "broadcast_date": args.broadcast_date or "",
        }
        if args.safari:
            page = read_safari_page()
            options["page_url"] = page["url"]
            success = download_audio_content(
                page["html"], urlsplit(page["url"]).hostname, download_directory, **options,
            )
        else:
            success = download_audio_from_html(
                str(Path(args.html).expanduser()), args.domain, download_directory, **options,
            )
        return 0 if success else 1
    except (OSError, RuntimeError) as exc:
        print(f"エラー: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
