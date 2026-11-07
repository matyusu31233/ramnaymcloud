#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RamNaym Cloud 免费容器自动续期
项目: https://www.ramnaymcloud.com/manage/<PROJECT_ID>

真实续期流程（2026-11-07 登录实测走通一遍）:
  1. POST /login 登录。表单带隐藏字段 csrf_token，且 POST 必须带
     Referer/Origin 头，缺任何一个都会被 “Your security session expired”
     拒绝（看起来像密码错误）。
  2. GET /manage/<id> 读 “Time left: Xh Ym left”（标签与数值是分开的元素，
     解析时要先剥标签）。
  3. GET /free-renew/<id> 本身不续期，它 302 跳到广告商 blitz-ly.com，
     跳转地址的 url= 参数里带着真正的一次性完成地址
     /free-renew/complete/<token>。
  4. 等待约 25 秒（广告页的 Continue 倒计时是 20 秒），
     然后带会话 GET 那个 complete 地址，才真正续期。
  5. 续期效果是把过期时间【重置】为完成时刻起约 24 小时，
     不是在剩余时间上叠加（实测：续前 22h46m，续后 23h59m）。
     所以成功标准是回读 Time left 达到约 24 小时。

环境变量（GitHub Secrets）:
  RAMNAYM_USERNAME   必填，面板账号名
  RAMNAYM_PASSWORD   必填，面板密码
  RAMNAYM_PROJECT_ID 选填，默认 1264
  RENEW_BELOW_HOURS  选填，剩余低于多少小时才续，默认 12
  RENEW_WAIT_SECONDS 选填，拿令牌后等待秒数，默认 25
  TG_BOT_TOKEN       选填，Telegram 汇报
  TG_CHAT_ID         选填，Telegram 汇报
  RAMNAYM_BASE_URL   选填，默认 https://www.ramnaymcloud.com（本地测试用）

只用 Python 标准库，无第三方依赖。
"""

import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import html as htmlmod

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

try:
    RENEW_WAIT_SECONDS = int(os.environ.get("RENEW_WAIT_SECONDS", "25"))
except ValueError:
    RENEW_WAIT_SECONDS = 25

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener_noredirect = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cj), _NoRedirect()
)


def http(method, path, data=None, headers_extra=None, follow=True):
    """返回 (status, final_url, body_text, headers)。不抛异常。"""
    url = path if path.startswith("http") else BASE_URL + path
    headers = {"User-Agent": UA}
    if headers_extra:
        headers.update(headers_extra)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    op = opener if follow else opener_noredirect
    try:
        with op.open(req, timeout=30) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace"), resp.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.geturl(), e.read().decode("utf-8", "replace"), e.headers
        except Exception:
            return e.code, url, "", e.headers
    except Exception as e:
        return 0, url, f"__ERROR__ {e}", {}


# ---------------- Time left 解析 ----------------

TIME_LEFT_RE = re.compile(
    r"Time left:\s*(?:(\d+)\s*d(?:ays?)?\s*)?(?:(\d+)\s*h(?:ours?|rs?)?\s*)?(?:(\d+)\s*m(?:in(?:ute)?s?)?\s*)?left",
    re.IGNORECASE,
)
VALUE_RE = re.compile(
    r"(?:(\d+)\s*d(?:ays?)?\s*)?(?:(\d+)\s*h(?:ours?|rs?)?\s*)?(?:(\d+)\s*m(?:in(?:ute)?s?)?\s*)?left",
    re.IGNORECASE,
)


def _value_to_minutes(m):
    if m is None:
        return None
    if m.group(1) is None and m.group(2) is None and m.group(3) is None:
        return None
    d = int(m.group(1) or 0)
    h = int(m.group(2) or 0)
    mi = int(m.group(3) or 0)
    return d * 1440 + h * 60 + mi


def parse_time_left(html):
    """解析剩余时间 -> 总分钟数；读不到返回 None。

    页面上 “Time left:” 与数值是分开的元素，原始 HTML 里没有连续的
    “Time left: 22h 53m left”，所以依次尝试：原文直找 -> 剥标签后找 ->
    锚定 Time left 附近找 -> 全文匹配数值本身。
    """
    if not html:
        return None
    html = htmlmod.unescape(html)
    v = _value_to_minutes(TIME_LEFT_RE.search(html))
    if v is not None:
        return v
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    v = _value_to_minutes(TIME_LEFT_RE.search(text))
    if v is not None:
        return v
    idx = text.lower().find("time left")
    if idx >= 0:
        v = _value_to_minutes(VALUE_RE.search(text[idx : idx + 80]))
        if v is not None:
            return v
    return _value_to_minutes(VALUE_RE.search(text))


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


def debug_snippets(html):
    """解析失败时摘录原始 HTML 中与倒计时有关的片段（csrf 值打码）。"""
    if not html:
        return "（页面为空）"
    safe = re.sub(r'(name="csrf_token"\s+value=")[^"]+', r"\1<hidden>", html)
    out = [f"页面长度 {len(html)} 字节"]
    for kw in ("Time left", "expir", "countdown", "remaining"):
        idx = safe.lower().find(kw.lower())
        if idx < 0:
            out.append(f"[{kw}] 未找到")
        else:
            snippet = re.sub(r"\s+", " ", safe[max(0, idx - 120) : idx + 220])
            out.append(f"[{kw}] …{snippet}…")
    return "\n".join(out)


# ---------------- 面板交互 ----------------

def extract_flash(html):
    msgs = []
    for m in re.finditer(r'class="flash-message"[^>]*>(.*?)</div>', html or "", re.S):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in msgs:
            msgs.append(t)
    return "；".join(msgs)


def login():
    _, _, login_html, _ = http("GET", "/login")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_html or "")
    if not m:
        return False, "登录页上没找到 csrf_token（页面结构可能变了）"
    status, final_url, body, _ = http(
        "POST",
        "/login",
        data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrf_token": m.group(1),
        },
        headers_extra={"Referer": BASE_URL + "/login", "Origin": BASE_URL},
    )
    if status == 0:
        return False, "登录请求失败（网络错误）"
    pstatus, pfinal, phtml, _ = http("GET", f"/manage/{PROJECT_ID}")
    if pstatus == 0:
        return False, "登录后读取管理页失败（网络错误）"
    if "/login" in pfinal:
        flash = extract_flash(body) or extract_flash(phtml)
        detail = f"（面板提示：{flash}）" if flash else ""
        return False, f"登录未成功{detail}"
    return True, "登录成功"


def fetch_time_left():
    status, final_url, html, _ = http("GET", f"/manage/{PROJECT_ID}")
    if status == 0:
        return None, "读取管理页失败（网络错误）"
    if "/login" in final_url:
        return None, "会话已失效（被跳回登录页）"
    if status != 200:
        return None, f"管理页返回 HTTP {status}"
    left = parse_time_left(html)
    if left is None:
        return None, "管理页上没解析到 Time left。原始页面片段：\n" + debug_snippets(html)
    return left, html


def get_complete_url():
    """GET /free-renew/<id>，从跳转中拿到一次性 complete 地址。

    返回 (complete_url, blitz_url, error)
    """
    status, final_url, body, headers = http(
        "GET",
        f"/free-renew/{PROJECT_ID}",
        headers_extra={"Referer": f"{BASE_URL}/manage/{PROJECT_ID}"},
        follow=False,
    )
    if status == 0:
        return None, None, "请求续期入口失败（网络错误）"
    location = headers.get("Location") if headers else None
    candidates = []
    if location:
        candidates.append(location)
    for pat in (
        r"https?://blitz-ly\.com/[^\s\"'<>]+",
        r"https?://[^\s\"'<>]*?/free-renew/complete/[A-Za-z0-9_\-]+",
    ):
        for m in re.finditer(pat, body or ""):
            candidates.append(htmlmod.unescape(m.group(0)))
    for cand in candidates:
        if "/free-renew/complete/" in cand:
            return cand, None, None
        if "blitz-ly.com" in cand:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(cand).query)
            inner = (q.get("url") or [None])[0]
            if inner and "/free-renew/complete/" in inner:
                return inner, cand, None
    if location and "blitz-ly.com" in location:
        return None, location, "广告跳转里没找到 url= 完成地址（结构可能变了）"
    return None, None, f"续期入口没有跳向广告页（HTTP {status}，落点 {final_url}）"


def do_renew():
    """执行一遍完整续期流程。返回 (ok, message)。"""
    complete_url, blitz_url, err = get_complete_url()
    if err:
        return False, err
    if blitz_url:
        http("GET", blitz_url)
    if RENEW_WAIT_SECONDS > 0:
        time.sleep(RENEW_WAIT_SECONDS)
    status, final_url, _, _ = http(
        "GET",
        complete_url,
        headers_extra={"Referer": blitz_url or f"{BASE_URL}/manage/{PROJECT_ID}"},
    )
    if status == 0:
        return False, "访问 complete 地址失败（网络错误）"
    if "/login" in final_url:
        return False, "访问 complete 地址时会话已失效"
    return True, "已提交 complete 续期请求"


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

    ok, msg = do_renew()
    if not ok:
        report(f"❌ RamNaym 续期失败：{msg}")
        tg_send("\n".join(lines))
        return 1

    after, err = fetch_time_left()
    if after is None:
        report(f"⚠️ 已走完续期流程，但回读失败：{err}（不能确认是否续上）")
        tg_send("\n".join(lines))
        return 1

    # 成功标准（实测语义）：续期把剩余重置为约 24 小时。
    if after >= 23 * 60 and after > before:
        report(f"✅ 已续期，剩余已重置为 {fmt_minutes(after)}（约 24 小时）")
        tg_send("\n".join(lines))
        return 0

    report(
        f"❌ 续期未生效：续期后剩余 {fmt_minutes(after)}，没有回到约 24 小时"
        "（可能 complete 令牌被广告商校验拦截，或流程已变更）"
    )
    tg_send("\n".join(lines))
    return 1


if __name__ == "__main__":
    sys.exit(main())
