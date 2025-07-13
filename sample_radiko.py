import base64
import re
import subprocess
import urllib.request

auth_key = "bcd151073c03b352e1ef2fd66c32209da9ca0afa"

# typescriptで実行することにしたので途中です。


def auth1():
    url = "https://radiko.jp/v2/api/auth1"
    headers = {}
    auth_response = {}

    headers = {
        "User-Agent": "curl/7.56.1",
        "Accept": "*/*",
        "X-Radiko-App": "pc_html5",
        "X-Radiko-App-Version": "0.0.1",
        "X-Radiko-User": "dummy_user",
        "X-Radiko-Device": "pc",
    }
    req = urllib.request.Request(url, None, headers)
    res = urllib.request.urlopen(req)
    auth_response["body"] = res.read()
    auth_response["headers"] = res.info()
    return auth_response


def get_partial_key(auth_response):
    authtoken = auth_response["headers"]["x-radiko-authtoken"]
    offset = auth_response["headers"]["x-radiko-keyoffset"]
    length = auth_response["headers"]["x-radiko-keylength"]
    offset = int(offset)
    length = int(length)
    partialkey = auth_key[offset : offset + length]
    partialkey = base64.b64encode(partialkey.encode())

    # logging.info(f"authtoken: {authtoken}")
    # logging.info(f"offset: {offset}")
    # logging.info(f"length: {length}")
    # logging.info(f"partialkey: {partialkey}")

    return [partialkey, authtoken]


def auth2(partialkey, auth_token):
    url = "https://radiko.jp/v2/api/auth2"
    headers = {
        "X-Radiko-AuthToken": auth_token,
        "X-Radiko-Partialkey": partialkey,
        "X-Radiko-User": "dummy_user",
        "X-Radiko-Device": "pc",
    }
    req = urllib.request.Request(url, None, headers)
    res = urllib.request.urlopen(req)
    txt = res.read()
    area = txt.decode()
    print(txt)
    return area


# 以下の関数は直接ストリームを聞くようかもね
def gen_temp_chunk_m3u8_url(url, auth_token):
    headers = {
        "X-Radiko-AuthToken": auth_token,
    }
    req = urllib.request.Request(url, None, headers)
    res = urllib.request.urlopen(req)
    body = res.read().decode()
    lines = re.findall("^https?://.+m3u8$", body, flags=(re.MULTILINE))
    # embed()
    return lines[0]


def download_radiko(auth_token, station_id, start_time, end_time):
    try:
        url = "https://radiko.jp/v2/api/ts/playlist.m3u8"
        url += f"?station_id={station_id}&l=15&ft={start_time}&to={end_time}"
        cmd = [
            "ffmpeg",
            # "-loglevel",
            # "error",
            "-fflags",
            "+discardcorrupt",
            "-headers",
            f"X-Radiko-Authtoken: {auth_token}",
            "-i",
            url,
            "-bsf:a",
            "aac_adtstoasc",
            "-acodec",
            "copy",
            "test.m4a",
        ]

        # output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print("ffmpeg stderr:\n", result.stderr)
            raise RuntimeError("ffmpeg execution failed.")

        print("ffmpeg stdout:\n", result.stdout)

        # print("output: ", output)
    except Exception as e:
        print(e)
        return False
    return True


if __name__ == "__main__":
    res = auth1()
    ret = get_partial_key(res)
    token = ret[1]
    partialkey = ret[0]
    print("token: ", token)
    print("partialkey: ", partialkey)

    area = auth2(partialkey, token)
    print("area: ", area)

    # url = f'http://f-radiko.smartstream.ne.jp/{argv[1]}/_definst_/simul-stream.stream/playlist.m3u8'
    # 開始時間と終了時間は秒数までの指定
    # download_radiko(token, "LFR", "20250701173000", "20250701175000")
    download_radiko(token, "LFR", "20250701112000", "20250701113000")
