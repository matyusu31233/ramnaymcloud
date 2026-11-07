#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RamNaym Cloud 免费容器自动续期
项目: https://www.ramnaymcloud.com/manage/<PROJECT_ID>

续期方式（2026-11-07 登录后实测确认）:
  1. POST /login (username + password) 拿会话 Cookie
  2. GET  /manage/<id> 读页面上的 "Time left: Xh Ym left"
  3. GET  /free-renew/<id> 即续期 +24 小时（页面原文: Renewing adds 24 hours
     to your current expiry time. Repeat as often as you like）
  4. 再读一次 /manage/<id>，只有 Time left 真的变大了才算续上

环境变量（GitHub Secrets）:
  RAMNAYM_USERNAME   必填，面板账号名
  RAMNAYM_PASSWORD   必填，面板密码
  RAMNAYM_PROJECT_ID 选填，默认 1264
  RENEW_BELOW_HOURS  选填，剩余低于多少小时才续，默认 12
                     （续期是往当前到期时间上 +24h、可以叠加；设阈值是为了
                      不无意义地一直叠。workflow 每 6 小时跑一次，不会漏）
  TG_BOT_TOKEN       选填，Telegram 汇报
  TG_CHAT_ID         选填，Telegram 汇报
  RAMNAYM_BASE_URL   选填，默认 https://www.ramnaymcloud.com（本地测试用）

只用 Python 标准库，无第三方依赖。
"""

import os
import re
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("RAMNAYM_BASE_URL", "https://www.ramnaymcloud.com").rstrip("/")
USERNAME = os.environ.get("RAMNAYM_USERNAME", "")
PASSWORD = os.environ.get("RAMNAYM_PASSWORD", "")
PROJECT_ID = os.environ.get("RAMNAYM_PROJECT_ID", "1264").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

try:
    RENEW_BELOW_HOURS = float(os.environ.get("RENEW_BELOW_HOURS", "12"))
except ValueError:
    RENEW_BELOW_HOURS = 12.0

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def http(method, path, data=None, headers_extra=None):
    """返回 (status, final_url, body_text)。不抛异常，交给调用方判断。"""
    url = path if path.startswith("http") else BASE_URL + path
    headers = {"User-Agent": UA}
    if headers_extra:
        headers.update(headers_extra)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.geturl(), e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, url, ""
    except Exception as e:
        return 0, url, f"__ERROR__ {e}"


TIME_LEFT_RE = re.compile(
    r"Time left:\s*(?:(\d+)\s*d\s*)?(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?left",
    re.IGNORECASE,
)


def parse_time_left(html):
    """解析 'Time left: 23h 29m left' -> 总分钟数；读不到返回 None。"""
    m = TIME_LEFT_RE.search(html or "")
    if not m:
        return None
    d = int(m.group(1) or 0)
    h = int(m.group(2) or 0)
    mi = int(m.group(3) or 0)
    if d == 0 and h == 0 and mi == 0 and "0m" not in m.group(0):
        return None
    return d * 1440 + h * 60 + mi


def fmt_minutes(total):
    if total is None:
        return "?"
    d, rem = divmod(int(total), 1440)
    h, mi = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{mi}m")
    return " ".join(parts)


def extract_flash(html):
    """提取页面上的 flash-message 提示文本（登录失败原因就写在这里）。"""
    msgs = []
    for m in re.finditer(r'class="flash-message"[^>]*>(.*?)</div>', html or "", re.S):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in msgs:
            msgs.append(t)
    return "；".join(msgs)


def login():
    # 1) GET 登录页：种会话 Cookie，并取隐藏字段 csrf_token
    #    （2026-11-07 实测：登录表单带 csrf_token，缺了它服务器会以
    #     “Your security session expired” 拒绝登录，看起来像密码错误）
    _, _, login_html = http("GET", "/login")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_html or "")
    if not m:
        return False, "登录页上没找到 csrf_token（页面结构可能变了）"
    csrf_token = m.group(1)

    # 2) POST 登录。实测必须带 Referer/Origin，否则面板的 CSRF 校验
    #    会以 “Your security session expired” 拒绝（看起来像密码错误）。
    status, final_url, body = http(
        "POST",
        "/login",
        data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrf_token": csrf_token,
        },
        headers_extra={
            "Referer": BASE_URL + "/login",
            "Origin": BASE_URL,
        },
    )
    if status == 0:
        return False, "登录请求失败（网络错误）"

    # 3) 成功与否不看 POST 的跳转，实际探一次管理页才算数
    pstatus, pfinal, phtml = http("GET", f"/manage/{PROJECT_ID}")
    if pstatus == 0:
        return False, "登录后读取管理页失败（网络错误）"
    if "/login" in pfinal:
        flash = extract_flash(body) or extract_flash(phtml)
        detail = f"（面板提示：{flash}）" if flash else ""
        return False, f"登录未成功{detail}"
    return True, "登录成功"


def fetch_time_left():
    status, final_url, html = http("GET", f"/manage/{PROJECT_ID}")
    if status == 0:
        return None, "读取管理页失败（网络错误）"
    if "/login" in final_url:
        return None, "会话已失效（被跳回登录页）"
    if status != 200:
        return None, f"管理页返回 HTTP {status}"
    left = parse_time_left(html)
    if left is None:
        return None, "管理页上没解析到 Time left（页面结构可能变了）"
    return left, html


def tg_send(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=data
        )
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def main():
    lines = []
    def report(msg):
        print(msg)
        lines.append(msg)

    if not USERNAME or not PASSWORD:
        report("❌ 缺 RAMNAYM_USERNAME / RAMNAYM_PASSWORD，未执行")
        tg_send("\n".join(lines))
        return 1

    ok, msg = login()
    if not ok:
        report(f"❌ RamNaym 续期失败：{msg}")
        tg_send("\n".join(lines))
        return 1

    before, err = fetch_time_left()
    if before is None:
        report(f"❌ RamNaym 续期失败：{err}")
        tg_send("\n".join(lines))
        return 1
    report(f"RamNaym 项目 {PROJECT_ID}：续期前剩余 {fmt_minutes(before)}")

    if before > RENEW_BELOW_HOURS * 60:
        report(f"剩余充足（阈值 {RENEW_BELOW_HOURS:g}h），本次跳过")
        tg_send("\n".join(lines))
        return 0

    status, final_url, _ = http(
        "GET",
        f"/free-renew/{PROJECT_ID}",
        headers_extra={"Referer": f"{BASE_URL}/manage/{PROJECT_ID}"},
    )
    if status == 0:
        report("❌ 续期请求失败（网络错误）")
        tg_send("\n".join(lines))
        return 1
    if "/login" in final_url:
        report("❌ 续期时会话已失效")
        tg_send("\n".join(lines))
        return 1

    after, err = fetch_time_left()
    if after is None:
        report(f"⚠️ 已发出续期请求，但回读失败：{err}（不能确认是否续上）")
        tg_send("\n".join(lines))
        return 1

    # 证明标准：到期时间真的后移。续期是 +24h，允许几分钟的自然流逝误差。
    if after >= before + 23 * 60:
        report(f"✅ 已续期 +24h，续期后剩余 {fmt_minutes(after)}")
        tg_send("\n".join(lines))
        return 0

    report(
        f"❌ 续期未生效：续期后剩余 {fmt_minutes(after)}，没有比续期前多出约 24h"
        "（可能续期链接已变更或被限流）"
    )
    tg_send("\n".join(lines))
    return 1


if __name__ == "__main__":
    sys.exit(main())
