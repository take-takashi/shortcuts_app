import json
from unittest.mock import Mock

import pytest

from AudioInfoExtractor import get_extractor
from AudioInfoExtractor.vimeo_audio import VimeoAudioError, resolve_vimeo_audio


PLAYER = "https://player.vimeo.com/video/123?h=private-hash"
REFERER = "https://sp.aiko.pcan.us/"
MASTER = "https://cdn.example.com/signed/master.m3u8?token=secret"
MEDIA = "https://cdn.example.com/signed/audio/main.m3u8?token=secret"


def response(text):
    result = Mock()
    result.text = text
    return result


def config_page(**files):
    config = {"video": {"duration": 42}, "request": {"files": files}}
    return "<script>window.playerConfig = " + json.dumps(config) + "; other();</script>"


def hls_config():
    return {"default_cdn": "primary", "cdns": {"primary": {"url": MASTER}}}


def test_team_aiko_extracts_private_embed_and_radio_metadata():
    extractor = get_extractor("sp.aiko.pcan.us", logger=Mock())
    assert extractor is not None
    infos = extractor.get_audio_info('''
      <html><head><title>あじがとレディオ#232 | Team aiko</title>
      <meta property="og:image" content="https://sp.aiko.pcan.us/images/ogp.png">
      </head><body><h1></h1><section class="radio_content">
      <h2>あじがとレディオ#232</h2>
      <iframe src="//player.vimeo.com/video/123?h=private-hash&amp;autoplay=0"></iframe>
      <img src="//cdn.example.com/img/msg_movie_sp/cover.jpg">
      </section></body></html>
    ''')
    assert infos is not None and len(infos) == 1
    info = infos[0]
    assert info.audio_src == PLAYER + "&autoplay=0"
    assert info.source_type == "vimeo"
    assert info.program_name == "あじがとレディオ"
    assert info.episode_title == "あじがとレディオ#232"
    assert info.artist_name == "aiko"
    assert info.cover_image_url == "https://cdn.example.com/img/msg_movie_sp/cover.jpg"
    assert info.referer == REFERER
    assert info.broadcast_date == ""


@pytest.mark.parametrize("url", [
    "https://player.vimeo.com.evil.example/video/123",
    "javascript:alert(1)",
    "https://example.com/player.vimeo.com/video/123",
])
def test_team_aiko_ignores_non_vimeo_iframes(url):
    extractor = get_extractor("sp.aiko.pcan.us", logger=Mock())
    assert extractor is not None
    assert not extractor.get_audio_info(f'<title>Test</title><iframe src="{url}"></iframe>')


@pytest.mark.parametrize("domain", ["sp.aiko.pcan.us.evil.example", "not-aiko.pcan.us"])
def test_team_aiko_domain_matching_requires_hostname_boundary(domain):
    assert get_extractor(domain, logger=Mock()) is None


def test_resolver_uses_playlist_duration_when_video_duration_is_missing():
    session = Mock()
    session.get.side_effect = [
        response(config_page(hls=hls_config()).replace('"duration": 42', '"duration": null')),
        response('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/main.m3u8?token=secret"\n'),
        response("#EXTM3U\n#EXTINF:20.25,\nfirst.m4s\n#EXTINF:21.75,\nsecond.m4s\n#EXT-X-ENDLIST\n"),
    ]
    assert resolve_vimeo_audio(PLAYER, REFERER, session=session).duration == 42


def test_resolver_selects_audio_only_preserves_signed_url_and_referer():
    session = Mock()
    session.get.side_effect = [
        response(config_page(hls=hls_config())),
        response('''#EXTM3U
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",URI="subs.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="en",DEFAULT=NO,URI="english.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="日本語, original",LANGUAGE="ja",DEFAULT=YES,URI="audio/main.m3u8?token=secret"
#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc1.64002A,mp4a.40.2",AUDIO="audio"
video.m3u8
'''),
        response("#EXTM3U\n#EXTINF:42,\nsegment.m4s\n#EXT-X-ENDLIST\n"),
    ]
    source = resolve_vimeo_audio(PLAYER, REFERER, session=session)
    assert source.url == MEDIA
    assert source.duration == 42
    assert source.referer == REFERER
    assert [call.args[0] for call in session.get.call_args_list] == [PLAYER, MASTER, MEDIA]
    for call in session.get.call_args_list:
        assert call.kwargs["headers"]["Referer"] == REFERER
        assert call.kwargs["timeout"] == 30


def test_resolver_tries_next_cdn_when_default_has_no_audio():
    hls = hls_config()
    hls["cdns"]["backup"] = {"url": "https://backup.example.com/master.m3u8"}
    session = Mock()
    session.get.side_effect = [
        response(config_page(hls=hls)),
        response("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nvideo.m3u8\n"),
        response('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,DEFAULT=YES,URI="audio.m3u8"\n'),
        response("#EXTM3U\n#EXTINF:42,\naudio.m4s\n#EXT-X-ENDLIST\n"),
    ]
    source = resolve_vimeo_audio(PLAYER, REFERER, session=session)
    assert source.url == "https://backup.example.com/audio.m3u8"


@pytest.mark.parametrize("content", [
    '<html><title>Forbidden</title></html>',
    '<script>window.playerConfig = {bad json};</script>',
    config_page(dash={}),
])
def test_resolver_fails_clearly_without_supported_config(content):
    session = Mock()
    session.get.return_value = response(content)
    with pytest.raises(VimeoAudioError):
        resolve_vimeo_audio(PLAYER, REFERER, session=session)


@pytest.mark.parametrize("media", [
    "<html>Access denied</html>",
    '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXTINF:42,\nseg.m4s\n#EXT-X-ENDLIST',
    '#EXTM3U\n#EXTINF:42,\nseg.m4s',  # ライブ配信や途中のリストは対象外
])
def test_resolver_rejects_invalid_encrypted_or_live_playlist(media):
    session = Mock()
    session.get.side_effect = [
        response(config_page(hls=hls_config())),
        response('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/main.m3u8?token=secret"\n'),
        response(media),
    ]
    with pytest.raises(VimeoAudioError):
        resolve_vimeo_audio(PLAYER, REFERER, session=session)


@pytest.mark.parametrize("player,referer", [
    ("file:///etc/passwd", REFERER),
    ("https://example.com/video/123", REFERER),
    (PLAYER, "https://sp.aiko.pcan.us/\r\nInjected: value"),
])
def test_resolver_validates_urls_before_network_access(player, referer):
    session = Mock()
    with pytest.raises(VimeoAudioError):
        resolve_vimeo_audio(player, referer, session=session)
    session.get.assert_not_called()
