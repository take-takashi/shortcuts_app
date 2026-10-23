"""CD取り込みを起動し、曲と復元用ZIPをNotionへ登録する。"""

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

from MyNotionHelper.my_notion_helper import MyNotionHelper

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / "Library/Application Support/shortcuts_app"
logger = logging.getLogger("import-cd")


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save_json(path: Path, value: dict) -> None:
    """同じディレクトリで書き切ってから置き換え、中断時のJSON破損を防ぐ。"""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as target:
        json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)


@dataclass
class Album:
    root: Path
    report_sha256: str
    result: dict
    metadata: dict

    def file(self, entry: dict) -> Path:
        return self.root / entry["file"]


def load_album(directory: Path) -> Album:
    """移動済みの出力も、schema v2の相対パス・サイズ・SHA-256で検証する。"""
    root = directory.expanduser().resolve()
    report_path = root / "report.json"
    if report_path.is_symlink():
        raise ValueError("report.jsonがシンボリックリンクです。")
    report_bytes = report_path.read_bytes()
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    report = json.loads(report_bytes)
    result = report.get("result")
    if (
        report.get("schema_version") != 2
        or report.get("operation") != "import"
        or report.get("status") != "complete"
        or not isinstance(result, dict)
    ):
        raise ValueError("diskflowの完了済みschema v2出力を指定してください。")
    if (
        result.get("directory") != "aac"
        or result.get("archive_directory") != "capture"
        or result.get("metadata_tagged") is not True
        or result.get("loudness_normalized") is not True
    ):
        raise ValueError("完成AACとcaptureを含む出力ではありません。")
    seen = set()

    def verify(entry: dict, prefix: str) -> None:
        name = entry["file"]
        relative = PurePosixPath(name)
        if (
            not name.startswith(prefix + "/")
            or relative.is_absolute()
            or relative.as_posix() != name
            or ".." in relative.parts
            or "\\" in name
            or name in seen
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        ):
            raise ValueError(f"不正な成果物パス・ハッシュです: {name}")
        path = root / name
        if any(
            p.is_symlink()
            for p in (path, *path.parents)
            if p != root and p.is_relative_to(root)
        ):
            raise ValueError(f"シンボリックリンクは送信できません: {name}")
        if (
            not path.is_file()
            or not path.resolve().is_relative_to(root)
            or path.stat().st_size != entry["bytes"]
            or sha256(path) != entry["sha256"]
        ):
            raise ValueError(f"成果物が変更されています: {name}")
        seen.add(name)

    verify(result["album"], "aac")
    verify(result["artwork"], "aac")
    tracks = result["tracks"]
    if not tracks or result["track_count"] != len(tracks):
        raise ValueError("曲数が一致しません。")
    for number, track in enumerate(tracks, 1):
        if (
            type(track["number"]) is not int
            or track["number"] != number
            or not track["file"].endswith(".m4a")
        ):
            raise ValueError("曲順またはAACファイル名が不正です。")
        verify(track, "aac")
    for entry in result["archive"]:
        verify(entry, "capture")
    capture_files = {
        p.relative_to(root).as_posix()
        for p in (root / "capture").rglob("*")
        if not p.is_dir() or p.is_symlink()
    }
    expected = {entry["file"] for entry in result["archive"]}
    required = {
        "capture/audio.bin",
        "capture/toc.bin",
        "capture/recipe.json",
        "capture/metadata/album.json",
    }
    if capture_files != expected or not required.issubset(expected):
        raise ValueError(
            "captureのファイル一覧がreport.jsonと一致しません。未登録ファイルは送信しません。"
        )
    metadata = json.loads((root / result["album"]["file"]).read_bytes())
    if (
        not isinstance(metadata.get("title"), str)
        or not metadata["title"].strip()
        or not (metadata.get("album_artist") or metadata.get("artist"))
        or len(metadata["tracks"]) != len(tracks)
    ):
        raise ValueError("アルバム情報が不正です。")
    for track, meta in zip(tracks, metadata["tracks"], strict=True):
        if track["number"] != meta["number"] or track["title"] != meta["title"]:
            raise ValueError("AACとアルバム情報の曲順・タイトルが一致しません。")
    if (root / result["artwork"]["file"]).suffix.lower() not in {
        ".jpg",
        ".jpeg",
        ".png",
    }:
        raise ValueError("カバー画像はJPEGまたはPNGを指定してください。")
    if sha256(report_path) != report_hash:
        raise ValueError("検証中にreport.jsonが変更されました。")
    return Album(root, report_hash, result, metadata)


def verify_capture_zip(album: Album, path: Path) -> None:
    if path.is_symlink():
        raise ValueError("ZIPがシンボリックリンクです。")
    expected = {entry["file"]: entry for entry in album.result["archive"]}
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(expected) or len(archive.infolist()) != len(
            expected
        ):
            raise ValueError("ZIPの内容一覧がcaptureと一致しません。")
        for info in archive.infolist():
            entry = expected[info.filename]
            if info.file_size != entry["bytes"]:
                raise ValueError(f"ZIP内のサイズ不一致: {info.filename}")
            digest = hashlib.sha256()
            with archive.open(info) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != entry["sha256"]:
                raise ValueError(
                    f"ZIP内の音声・資料が変更されています: {info.filename}"
                )


def build_capture_zip(album: Album) -> Path:
    """capture/を丸ごと格納する。既存ZIPは検証し、上書きしない。"""
    target = album.root / "capture.zip"
    if target.exists() or target.is_symlink():
        verify_capture_zip(album, target)
        return target
    partial = album.root / f".capture-{uuid.uuid4().hex}.zip.partial"
    logger.info("原本ZIPを作成します: %s", target)
    with zipfile.ZipFile(
        partial,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        strict_timestamps=False,
    ) as archive:
        for entry in album.result["archive"]:
            archive.write(album.file(entry), entry["file"])
    verify_capture_zip(album, partial)
    # linkは既存targetを上書きしない。失敗時のpartialは調査用に残す。
    os.link(partial, target)
    partial.unlink()
    return target


class Journal:
    """成功済み操作を再送しない。結果不明のページ作成・追加は自動再試行しない。"""

    def __init__(
        self,
        album: Album,
        music_db: str,
        tags_db: str,
        *,
        retry_uncertain: bool = False,
    ):
        self.path = album.root / "notion-upload.json"
        identity = {
            "schema_version": 1,
            "report_sha256": album.report_sha256,
            "music_database_id": music_db,
            "tags_database_id": tags_db,
        }
        if self.path.is_symlink():
            raise ValueError("再開情報がシンボリックリンクです。")
        if self.path.exists():
            self.data = json.loads(self.path.read_bytes())
            if any(self.data.get(key) != value for key, value in identity.items()):
                raise ValueError("再開情報とアルバム・Notion設定が一致しません。")
        else:
            self.data = {**identity, "status": "running", "steps": {}, "pending": None}
            with self.path.open("x", encoding="utf-8") as target:
                json.dump(self.data, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
        pending = self.data.get("pending")
        if pending and pending["unsafe"] and not retry_uncertain:
            raise RuntimeError(
                f"前回の「{pending['key']}」の結果が不明です。Notionページを確認してください。未実行または重複分を整理したことを確認後、--retry-uncertainで再開できます。"
            )
        if pending:
            self.data["pending"] = None
            self.save()

    def save(self):
        save_json(self.path, self.data)

    def step(self, key, operation, *, unsafe=False):
        if key in self.data["steps"]:
            return self.data["steps"][key]
        logger.info("Notion: %s", key)
        self.data.update(status="running", pending={"key": key, "unsafe": unsafe})
        self.save()
        try:
            value = operation()
        except BaseException as exc:
            # 明示的な4xx拒否と、実体送信・置換操作は安全に再試行できる。
            response = getattr(exc, "response", None)
            status = getattr(exc, "status", None) or getattr(
                response, "status_code", None
            )
            rejected = isinstance(status, int) and 400 <= status < 500 and status != 408
            if not unsafe or rejected:
                self.data["pending"] = None
            self.data["status"] = "failed"
            self.save()
            raise
        self.data["steps"][key] = value
        self.data["pending"] = None
        self.save()
        return value


def upload_album(
    album: Album, archive: Path, helper: MyNotionHelper, journal: Journal
) -> None:
    if journal.data["status"] == "complete":
        return
    limit = helper.get_max_upload_size()
    for path in (
        archive,
        album.file(album.result["artwork"]),
        *(album.file(t) for t in album.result["tracks"]),
    ):
        if path.stat().st_size > limit:
            raise ValueError(
                f"Notionの1ファイル上限を超えています: {path.name} ({path.stat().st_size:,} bytes / 上限 {limit:,} bytes)。分割送信でもプラン上限は変わりません。ローカル原本は保持します。"
            )
    step = journal.step
    title = album.metadata["title"]
    artist = album.metadata.get("album_artist") or album.metadata["artist"]
    album_id = step(
        "album_tag",
        lambda: helper.get_or_create_tag_page(
            journal.data["tags_database_id"], title, "音楽", strict=True
        ),
        unsafe=True,
    )
    cover_name = f"cover-{album.result['artwork']['sha256'][:12]}{album.file(album.result['artwork']).suffix.lower()}"
    zip_name = f"capture-{album.report_sha256[:12]}.zip"

    expected_hashes = {
        album.file(entry): entry["sha256"]
        for entry in [album.result["artwork"], *album.result["tracks"]]
    }
    expected_hashes[archive] = sha256(archive)

    def send(path):
        if path.is_symlink() or sha256(path) != expected_hashes[path]:
            raise ValueError(f"送信前にファイルが変更されました: {path.name}")
        upload_id = helper.upload_file_data(str(path))
        if sha256(path) != expected_hashes[path]:
            raise ValueError(
                f"送信中にファイルが変更されました。添付しません: {path.name}"
            )
        return upload_id

    def upload(key, path, attach_key):
        # 添付前に1時間以上経過していたら、その実体だけを送り直す。
        previous = journal.data["steps"].get(key)
        if (
            previous
            and attach_key not in journal.data["steps"]
            and not helper.file_upload_is_ready(previous)
        ):
            del journal.data["steps"][key]
            journal.save()
        return step(key, partial(send, path))

    # 画像はZIPより先に送信・添付し、本文の先頭とアイコンに使う。
    cover_id = upload(
        "cover_upload", album.file(album.result["artwork"]), "cover_block"
    )
    cover_block = step(
        "cover_block",
        lambda: helper.attach_uploaded_file(
            album_id, cover_id, cover_name, "image", position={"type": "start"}
        ),
        unsafe=True,
    )
    step("icon", lambda: helper.set_page_icon(album_id, cover_id))
    zip_id = upload("zip_upload", archive, "zip_block")
    step(
        "zip_block",
        lambda: helper.attach_uploaded_file(
            album_id,
            zip_id,
            zip_name,
            "file",
            position={"type": "after_block", "after_block": {"id": cover_block}},
        ),
        unsafe=True,
    )
    refs = [
        MyNotionHelper.upload_reference(cover_name, cover_id),
        MyNotionHelper.upload_reference(zip_name, zip_id),
    ]
    step(
        "album_files", lambda: helper.update_file_property(album_id, refs, prepend=True)
    )
    artist_id = step(
        "artist_tag",
        lambda: helper.get_or_create_tag_page(
            journal.data["tags_database_id"], artist, "音楽", strict=True
        ),
        unsafe=True,
    )
    for track, meta in zip(
        album.result["tracks"], album.metadata["tracks"], strict=True
    ):
        key = f"track_{track['number']:02d}"
        metadata = {
            "title": track["title"],
            "album": title,
            "album_artist": artist,
            "artist": meta.get("artist") or album.metadata.get("artist") or artist,
            "track": f"{track['number']}/{len(album.result['tracks'])}",
        }
        page_id = step(
            key + "_page",
            partial(
                helper.create_music_page,
                metadata,
                journal.data["music_database_id"],
                album_id,
                artist_id,
            ),
            unsafe=True,
        )
        path = album.file(track)
        upload_id = upload(key + "_upload", path, key + "_block")
        step(
            key + "_block",
            partial(
                helper.attach_uploaded_file, page_id, upload_id, path.name, "audio"
            ),
            unsafe=True,
        )
        step(
            key + "_files",
            partial(
                helper.update_file_property,
                page_id,
                [MyNotionHelper.upload_reference(path.name, upload_id)],
            ),
        )
    journal.data.update(status="complete", pending=None)
    journal.save()


def find_mise() -> Path:
    candidates = [
        shutil.which("mise"),
        str(Path.home() / ".local/bin/mise"),
        "/opt/homebrew/bin/mise",
        "/usr/local/bin/mise",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate)
    raise RuntimeError("miseが見つかりません。miseをインストールしてください。")


def run_diskflow(
    mise: Path,
    project: Path,
    output: Path,
    artwork: Path | None,
    search: str | None,
    source: Path | None,
    non_interactive: bool,
) -> dict:
    command = [
        str(mise),
        "-C",
        str(project),
        "run",
        "import",
        "--",
        "--output",
        str(output),
    ]
    if source:
        command.append(str(source))
    if artwork:
        command += ["--artwork", str(artwork)]
    if search:
        command += ["--search", search]
    if non_interactive:
        command.append("--non-interactive")
    # 呼び出し元のusage変数・仮想環境をdiskflowへ持ち込まない。
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("usage_", "NOTION_"))
        and key not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    result = subprocess.run(
        command, cwd=project, env=env, stdout=subprocess.PIPE, text=True, check=False
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"diskflowからJSON結果を取得できません。保存先: {output}"
        ) from exc
    if result.returncode != 0 or report.get("status") != "complete":
        raise RuntimeError(
            f"diskflowの取り込みが失敗しました: {report.get('error', result.returncode)}。保存先: {output}"
        )
    return report


def make_notion_helper() -> tuple[MyNotionHelper, str, str]:
    load_dotenv(SCRIPT_DIR / ".env")
    names = ("NOTION_TOKEN", "NOTION_DATABASE_MUSIC_ID", "NOTION_DATABASE_TAGS_ID")
    values = [os.environ.get(name, "").strip() for name in names]
    if not all(values):
        raise ValueError(
            "shortcuts_app/.envにNOTION_TOKEN・NOTION_DATABASE_MUSIC_ID・NOTION_DATABASE_TAGS_IDを設定してください。"
        )
    return MyNotionHelper(values[0], logger=logger), values[1], values[2]


@contextmanager
def import_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "import-cd.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("別のCD取り込みが実行中です。") from exc
        yield


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="CDからAACを作成し、曲と原本ZIPをNotionへ登録します。"
    )
    result.add_argument(
        "album",
        nargs="?",
        type=Path,
        help="完了済みdiskflow出力。CDなしでアップロードを開始・再開",
    )
    result.add_argument("--artwork", type=Path, help="取り込みに使うJPEG/PNG")
    result.add_argument("--search", help="アーティスト名・アルバム名")
    result.add_argument(
        "--output", type=Path, help="新規取り込み先（省略時は~/Music/diskflow/）"
    )
    result.add_argument(
        "--from-capture", type=Path, help="CDの代わりに保存済みcaptureからAACを再生成"
    )
    result.add_argument(
        "--prepare-only",
        action="store_true",
        help="AACとZIPまで作成。Notionへは接続しない",
    )
    result.add_argument(
        "--non-interactive", action="store_true", help="選択・入力が必要なら停止"
    )
    result.add_argument(
        "--retry-uncertain",
        action="store_true",
        help="Notion上の結果を手動確認・整理したうえで結果不明の操作を再試行",
    )
    result.add_argument(
        "--diskflow",
        type=Path,
        default=Path(
            os.environ.get("DISKFLOW_DIR", str(SCRIPT_DIR.parent / "diskflow"))
        ),
        help=argparse.SUPPRESS,
    )
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    handlers = []
    root = None
    try:
        if args.album and (
            args.artwork or args.search or args.output or args.from_capture
        ):
            raise ValueError(
                "完了済み出力の再開時は、取り込み用オプションを指定しないでください。"
            )
        logger.setLevel(logging.INFO)
        console = logging.StreamHandler(sys.stderr)
        logger.addHandler(console)
        handlers.append(console)
        with import_lock():
            notion = None if args.prepare_only else make_notion_helper()
            root = args.album.expanduser().resolve() if args.album else None
            previous = STATE_DIR / "import-cd-last.json"
            # Spotlightから再起動した場合も、アップロード途中の出力を選び直せる。
            if (
                root is None
                and not args.from_capture
                and not args.output
                and not args.artwork
                and not args.search
                and previous.exists()
                and sys.stdin.isatty()
                and not args.non_interactive
            ):
                last = Path(json.loads(previous.read_bytes())["album"])
                state_path = last / "notion-upload.json"
                if (
                    state_path.exists()
                    and json.loads(state_path.read_bytes()).get("status") != "complete"
                ):
                    print(
                        f"未完了の取り込みがあります: {last}\n続きから再開しますか？ [y/N]: ",
                        file=sys.stderr,
                        end="",
                        flush=True,
                    )
                    if sys.stdin.readline().strip().lower() in {"y", "yes"}:
                        root = last
            if root is None:
                root = (
                    (
                        args.output
                        or Path.home()
                        / "Music/diskflow"
                        / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
                    )
                    .expanduser()
                    .resolve()
                )
                if root.exists() or root.is_symlink():
                    raise FileExistsError(f"新しい保存先を指定してください: {root}")
                print(f"取り込み先: {root}", file=sys.stderr)
                run_diskflow(
                    find_mise(),
                    args.diskflow.expanduser().resolve(),
                    root,
                    args.artwork.expanduser().resolve() if args.artwork else None,
                    args.search,
                    args.from_capture.expanduser().resolve()
                    if args.from_capture
                    else None,
                    args.non_interactive,
                )
            album = load_album(root)
            save_json(previous, {"album": str(root)})
            log_path = root / "notion-upload.log"
            if log_path.is_symlink():
                raise ValueError("ログ出力先がシンボリックリンクです。")
            file_log = logging.FileHandler(log_path, encoding="utf-8")
            file_log.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(file_log)
            handlers.append(file_log)
            archive = build_capture_zip(album)
            if notion is None:
                status = "prepared"
                page_id = None
            else:
                helper, music_db, tags_db = notion
                journal = Journal(
                    album, music_db, tags_db, retry_uncertain=args.retry_uncertain
                )
                upload_album(album, archive, helper, journal)
                status = "complete"
                page_id = journal.data["steps"]["album_tag"]
            output = {
                "schema_version": 1,
                "status": status,
                "album_directory": str(root),
                "aac_directory": str(root / "aac"),
                "archive": str(archive),
                "archive_sha256": sha256(archive),
                "album_tag_page_id": page_id,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            print(
                f"{'準備' if notion is None else '登録'}が完了しました: {root}",
                file=sys.stderr,
            )
            return 0
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "error": "中断しました。ローカルファイルは保持します。",
                },
                ensure_ascii=False,
            )
        )
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "error": str(exc),
                    "album_directory": str(root) if root else None,
                },
                ensure_ascii=False,
            )
        )
        print(f"失敗: {exc}", file=sys.stderr)
        if root and (root / "report.json").exists():
            print(
                f"アップロードの再開: mise run import-cd {shlex.quote(str(root))}",
                file=sys.stderr,
            )
        return 1
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
