"""Vimeoの埋め込み設定から、暗号化されていない音声専用HLSを選択する。"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests


class VimeoAudioError(RuntimeError):
    """Vimeoの配信設定を取得できない、または未対応の配信方式。"""


@dataclass(frozen=True)
class VimeoAudioSource:
    url: str
    referer: str
    duration: float | None


def _validate_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username or parsed.password or any(c in url for c in "\r\n")):
        raise VimeoAudioError("配信URLまたはRefererが不正です。")


def _get_text(session, url: str, referer: str) -> str:
    _validate_http_url(url)
    try:
        response = session.get(url, headers={"Referer": referer}, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        # 例外に含まれる署名付き配信URLをログに残さない。
        raise VimeoAudioError("Vimeoの配信情報を取得できませんでした。ページを開き直して再試行してください。") from None


def _player_config(html: str) -> dict:
    match = re.search(r"(?:window\.)?playerConfig\s*=\s*", html)
    if not match:
        raise VimeoAudioError("Vimeoのプレーヤー設定がありません。ログイン状態や埋め込みの視聴制限を確認してください。")
    try:
        # JavaScriptは実行せず、代入されているJSONだけを読み取る。
        config, _ = json.JSONDecoder().raw_decode(html[match.end():])
        if not isinstance(config, dict):
            raise ValueError
        return config
    except (ValueError, TypeError):
        raise VimeoAudioError("Vimeoのプレーヤー設定を解析できませんでした。") from None


def _attributes(line: str) -> dict[str, str]:
    return {
        key: value[1:-1] if value.startswith('"') else value
        for key, value in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line)
    }


def _validate_playlist(text: str, *, media: bool = False) -> None:
    if not text.lstrip().startswith("#EXTM3U"):
        raise VimeoAudioError("HLSプレイリストを取得できませんでした。")
    for line in text.splitlines():
        if line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            if _attributes(line).get("METHOD") != "NONE":
                raise VimeoAudioError("暗号化されたHLS配信には対応していません。")
    if media and ("#EXT-X-ENDLIST" not in text or "#EXTINF:" not in text):
        raise VimeoAudioError("完結した音声のHLSではありません。ライブ配信には対応していません。")


def _audio_rendition(master: str, master_url: str) -> str:
    _validate_playlist(master)
    audios = []
    for line in master.splitlines():
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = _attributes(line)
            if attrs.get("TYPE") == "AUDIO" and attrs.get("URI"):
                audios.append(attrs)
    if not audios:
        raise VimeoAudioError("音声専用のHLSトラックがありません。")
    # 日本語と既定のトラックを優先し、動画や字幕のデータは取得しない。
    selected = max(audios, key=lambda a: (
        a.get("LANGUAGE", "").lower().startswith("ja"),
        a.get("DEFAULT") == "YES",
        "high" in a.get("GROUP-ID", "").lower(),
    ))
    url = urljoin(master_url, selected["URI"])
    _validate_http_url(url)
    return url


def resolve_vimeo_audio(
    player_url: str, referer: str, *, session=None,
) -> VimeoAudioSource:
    """非公開動画のhパラメータを維持し、現在の配信URLを取得する。"""
    _validate_http_url(player_url)
    _validate_http_url(referer)
    parsed = urlsplit(player_url)
    if parsed.hostname != "player.vimeo.com" or not re.fullmatch(r"/video/\d+/?", parsed.path):
        raise VimeoAudioError("Vimeoの埋め込みURLを指定してください。")

    if session is None:
        with requests.Session() as owned_session:
            return resolve_vimeo_audio(player_url, referer, session=owned_session)

    config = _player_config(_get_text(session, player_url, referer))
    files = config.get("request", {}).get("files", {})
    hls = files.get("hls") or {}
    cdns = hls.get("cdns") or {}
    if not cdns:
        raise VimeoAudioError("VimeoのHLS配信設定がありません。")
    duration = config.get("video", {}).get("duration")
    duration = float(duration) if isinstance(duration, (float, int)) and duration > 0 else None

    # 既定CDNが利用できない場合のみ、設定に含まれる別CDNを試す。
    names = sorted(cdns, key=lambda name: name != hls.get("default_cdn"))
    last_error = None
    for name in names:
        master_url = cdns[name].get("url")
        if not master_url:
            continue
        try:
            master = _get_text(session, master_url, referer)
            audio_url = _audio_rendition(master, master_url)
            media = _get_text(session, audio_url, referer)
            _validate_playlist(media, media=True)
            # 動画側に長さがない場合も、HLSの各区間の合計で完全性を確認する。
            expected = duration or sum(
                float(value) for value in re.findall(r"(?m)^#EXTINF:([\d.]+)", media)
            )
            return VimeoAudioSource(url=audio_url, referer=referer, duration=expected)
        except VimeoAudioError as exc:
            last_error = exc
    raise last_error or VimeoAudioError("利用できる音声専用HLSがありません。")
