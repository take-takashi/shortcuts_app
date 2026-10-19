from unittest.mock import Mock

import pytest
import requests

from AudioInfoExtractor.team_aiko import (
    TeamAikoDateError,
    normalize_publication_date,
    resolve_team_aiko_publish_date,
)


PAGE = "https://sp.aiko.pcan.us/contents/messagemovie.php?msg_movie_id=305&mc_id=8"
LIST = "https://sp.aiko.pcan.us/contents/messagemovielist.php?mc_id=8"
DETAIL = '<h2>あじがとレディオ#232</h2><a href="messagemovielist.php?mc_id=8">LIST</a>'


def item(episode_id="305", title="あじがとレディオ#232", date="2026.10.08"):
    return f'''<li><a href="messagemovie.php?msg_movie_id={episode_id}&amp;mc_id=8">
      <div class="movie_title"><time>{date}</time><div class="bold large">{title}</div></div>
    </a></li>'''


def response(html):
    result = Mock()
    result.content = html.encode("utf-8")
    return result


@pytest.mark.parametrize("value", ["20261008", "2026-10-08", "2026.10.08", "2026/10/08"])
def test_normalize_publication_date(value):
    assert normalize_publication_date(value) == "20261008"


@pytest.mark.parametrize("value", ["2026-02-30", "today", "", "2026-10-08 extra", "2026111", "261008"])
def test_reject_invalid_publication_date(value):
    with pytest.raises(ValueError):
        normalize_publication_date(value)


def test_publication_date_is_matched_by_episode_id_not_other_dates():
    session = Mock()
    session.get.return_value = response(
        '<footer><time>2026.10.19</time></footer>'
        + item("304", "あじがとレディオ#231", "2026.10.01")
        + item(title="一覧側で変更されたタイトル")
    )
    assert resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session) == "20261008"
    session.get.assert_called_once_with(LIST, headers={"Referer": PAGE}, timeout=30)


def test_saved_html_without_page_url_matches_exact_episode_title():
    session = Mock()
    session.get.return_value = response(item("300", "あじがとレディオ#23", "2025.01.01") + item())
    assert resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", session=session) == "20261008"


def test_pagination_finds_older_episode_and_ignores_external_next_link():
    session = Mock()
    session.get.side_effect = [
        response(item("306", "あじがとレディオ#233", "2026.10.15")
                 + '<a href="https://evil.example/contents/messagemovielist.php?page_no=2">NEXT</a>'
                 + '<a href="messagemovielist.php?mc_id=8&amp;page_no=2">NEXT</a>'),
        response(item()),
    ]
    assert resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session) == "20261008"
    assert session.get.call_args_list[1].args[0] == LIST + "&page_no=2"


def test_known_episode_id_does_not_fall_back_to_matching_title_of_another_episode():
    session = Mock()
    session.get.return_value = response(item("999"))
    with pytest.raises(TeamAikoDateError, match="公開日"):
        resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session)


@pytest.mark.parametrize("listing", [
    '<html>ログインしてください</html>',
    item(date="2026.02.30"),
    item(date=""),
    item().replace("<time>2026.10.08</time>", ""),
])
def test_missing_or_invalid_date_is_not_replaced_with_today(listing):
    session = Mock()
    session.get.return_value = response(listing)
    with pytest.raises(TeamAikoDateError, match="公開日"):
        resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session)


def test_network_errors_are_reported_with_manual_date_hint():
    session = Mock()
    session.get.side_effect = requests.Timeout()
    with pytest.raises(TeamAikoDateError, match="--broadcast-date"):
        resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session)


def test_looping_pagination_is_bounded():
    session = Mock()
    session.get.side_effect = [
        response('<a href="messagemovielist.php?mc_id=8&amp;page_no=2">NEXT</a>'),
        response('<a href="messagemovielist.php?mc_id=8&amp;page_no=2">NEXT</a>'),
    ]
    with pytest.raises(TeamAikoDateError):
        resolve_team_aiko_publish_date(DETAIL, "あじがとレディオ#232", page_url=PAGE, session=session)
    assert session.get.call_count == 2
