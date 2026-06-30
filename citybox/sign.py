#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CITYBOX 魔盒 微信小程序签到 - Python 版本

由以下两个 GitHub JavaScript 脚本合并转换而来:
  1. FboZhu/QX/js/MH_CityBox.js          (https://github.com/FboZhu/QX)
  2. axtyet/Luminous/.../citybox.js       (https://github.com/axtyet/Luminous)

================================================================
登录信息是怎么传入的 (关键说明)
================================================================
CityBox (CITYBOX 魔盒) 是微信小程序, 登录态完全靠 HTTP 请求头里的两个字段:
  - `token`:  用户身份令牌 (必填)
  - `sign` :  API 签名      (脚本1 必填; 脚本2 因整体复用 HAR headers 不显式区分)

获取方式 (抓包):
  1. 用 Charles / Fiddler / Stream / Proxyman 等工具代理手机流量
  2. 打开 CITYBOX 魔盒小程序, 触发任意请求 (例如打开"我的"页面会调 get_user_info)
  3. 在抓到的任一请求 https://api.icitybox.cn/api/... 的请求头里复制:
       token: xxxx
       sign : xxxx        # 部分版本接口需要
  4. 把这两个值填到 config.json / 环境变量 / 命令行参数

================================================================
使用方式
================================================================
方式 A: 配置文件 (推荐, 支持多账号)
    python sign.py --config config.json

方式 B: 环境变量 (适合 cron / Docker, 推荐用编号方式)
    # 编号方式 (推荐, 无需写 JSON, 允许跳号临时禁用某账号)
    set CITYBOX_ACCOUNTS_TOKEN1=xxx
    set CITYBOX_ACCOUNTS_SIGN1=yyy
    set CITYBOX_ACCOUNTS_REMARK1=主号
    # 跳过 1 只用 2 也可以 (1 被临时禁用)
    set CITYBOX_ACCOUNTS_TOKEN2=aaa
    set CITYBOX_ACCOUNTS_SIGN2=bbb
    set CITYBOX_ACCOUNTS_REMARK2=小号
    python sign.py

    # 或 JSON 数组方式 (兼容旧版)
    set CITYBOX_ACCOUNTS=[{"token":"xxx","sign":"yyy","remark":"main"}]
    python sign.py

方式 C: 命令行单账号
    python sign.py --token xxxx --sign yyyy

================================================================
通知 (可选, 命令行参数和环境变量二选一, 命令行优先)
================================================================
通用 webhook:
    python sign.py --config config.json --webhook https://your.webhook/url
    # 或
    set SIGNHUB_WEBHOOK_URL=https://your.webhook/url
    python sign.py --config config.json

PushPlus 一对多群组推送 (参考 https://pushplus.plus/doc/guide/api.html):
    # 仅发给自己
    python sign.py --config config.json --pp-token <你的pushplus_token>

    # 发给指定群组 (一对多)
    python sign.py --config config.json --pp-token <token> --pp-topic <群组编码>

    # 用 markdown 模板
    python sign.py --config config.json --pp-token <token> --pp-topic <群组编码> --pp-template markdown

    # 也可以全部用环境变量 (适合 cron / Docker)
    set SIGNHUB_PUSHPLUS_TOKEN=<token>
    set SIGNHUB_PUSHPLUS_TOPIC=<群组编码>
    set SIGNHUB_PUSHPLUS_TEMPLATE=markdown
    python sign.py --config config.json

================================================================
依赖
================================================================
    pip install requests
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "[FATAL] 缺少依赖 requests, 请先执行:  pip install requests\n"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# 常量配置 (与 JS 脚本对照)
# ---------------------------------------------------------------------------
# 脚本1 用 /api/...  脚本2 用 /index.php/api/...  服务端通常两者都兼容
BASE_URL = "https://api.icitybox.cn"
PATH_USER_INFO = "/api/user/get_user_info"
PATH_SIGN = "/api/user/up_sign"
PATH_DRAW = "/api/roulette_draw/draw_results"

# 脚本1 抓包默认 sign (作为兜底, 实际请用抓到的最新值)
FALLBACK_SIGN = "d7f1086401306ebdfd494b9be389c28c"

# 脚本1 中抓包得到的默认请求头 (微信 Mac 小程序环境)
DEFAULT_HEADERS: dict[str, str] = {
    "Host": "api.icitybox.cn",
    "accept": "application/json, text/plain, */*",
    "xweb_xhr": "1",
    "cb-mini-version": "8.1.49",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.7(0x13080712) "
        "UnifiedPCMacWechat(0xf26415f0) XWEB/17078"
    ),
    "channel": "mini",
    "content-type": "application/x-www-form-urlencoded",
    "platform-id": "1",
    "platform": "wap",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "referer": "https://servicewechat.com/wx8434e31068c20849/854/page-frame.html",
    "accept-language": "zh-CN,zh;q=0.9",
    "priority": "u=1, i",
}

# 接口间随机延时 (毫秒) —— 对应 JS 脚本1 CONFIG.MIN/MAX_WAIT_TIME
MIN_WAIT_MS = 2000
MAX_WAIT_MS = 5000

REQUEST_TIMEOUT = 15  # 秒


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class ClientOptions:
    """HTTP 客户端全局选项。"""
    verify_ssl: bool = True          # 是否校验 SSL 证书
    proxy: str | None = None         # 自定义代理, 例如 http://127.0.0.1:8888
    trust_env: bool = False          # 是否读取系统代理环境变量 (默认关闭, 避免 Fiddler 干扰)


@dataclass
class Account:
    """单个 CityBox 账号配置。"""
    token: str
    sign: str = ""
    remark: str = ""  # 备注名, 仅用于日志
    extra_headers: dict[str, str] = field(default_factory=dict)

    def headers(self) -> dict[str, str]:
        h = dict(DEFAULT_HEADERS)
        h["token"] = self.token
        h["sign"] = self.sign or FALLBACK_SIGN
        # 允许用户覆盖任意 header (例如换 UA / referer)
        h.update(self.extra_headers)
        return h


@dataclass
class AccountResult:
    remark: str
    user_info_before: str = ""
    sign_msg: str = ""
    draw_msgs: list[str] = field(default_factory=list)
    user_info_after: str = ""
    error: str = ""

    def summary(self) -> str:
        lines = [f"=== 账号: {self.remark} ==="]
        if self.error:
            lines.append(f"  [错误] {self.error}")
            return "\n".join(lines)
        if self.user_info_before:
            lines.append(f"  签到前: {self.user_info_before}")
        if self.sign_msg:
            lines.append(f"  签到  : {self.sign_msg}")
        for i, m in enumerate(self.draw_msgs, 1):
            lines.append(f"  抽奖{i}: {m}")
        if self.user_info_after:
            lines.append(f"  签到后: {self.user_info_after}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------
class CityBoxClient:
    """CityBox API 客户端, 对应 JS 脚本中的 $nobyda.get / $nobyda.post。"""

    def __init__(self, account: Account, options: ClientOptions | None = None, logger=None) -> None:
        self.account = account
        self.options = options or ClientOptions()
        self.session = requests.Session()
        self.session.headers.update(account.headers())
        # 关键: 默认不读取系统代理 (避免 Fiddler/Charles 残留代理导致 SSL 失败)
        self.session.trust_env = self.options.trust_env
        if self.options.proxy:
            self.session.proxies = {
                "http": self.options.proxy,
                "https": self.options.proxy,
            }
        # SSL 校验开关
        self.session.verify = self.options.verify_ssl
        # urllib3 警告: 关闭 SSL 关闭时的 InsecureRequestWarning
        if not self.options.verify_ssl:
            try:
                from urllib3 import disable_warnings
                from urllib3.exceptions import InsecureRequestWarning
                disable_warnings(InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass
        self.log = logger or (lambda msg: print(msg, flush=True))

    # ---- 工具 ----
    @staticmethod
    def _wait_ms() -> int:
        return random.randint(MIN_WAIT_MS, MAX_WAIT_MS)

    def _sleep_random(self) -> None:
        ms = self._wait_ms()
        self.log(f"    休息 {ms} ms ...")
        time.sleep(ms / 1000)

    @staticmethod
    def _parse(data: str) -> dict[str, Any]:
        try:
            return json.loads(data)
        except Exception as e:
            return {"_raw": data, "_parse_error": str(e)}

    # ---- 接口 ----
    def get_user_info(self) -> dict[str, Any]:
        """对应 JS: UserInfo()  -> /api/user/get_user_info"""
        url = BASE_URL + PATH_USER_INFO
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        return self._parse(resp.text)

    def sign(self) -> dict[str, Any]:
        """对应 JS: CityBoxSign() -> /api/user/up_sign?ts=<ms>"""
        ts = int(time.time() * 1000)
        url = f"{BASE_URL}{PATH_SIGN}?ts={ts}"
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        return self._parse(resp.text)

    def draw(self, click_num: int | None = None) -> dict[str, Any]:
        """对应 JS: DrawResults() -> POST /api/roulette_draw/draw_results
        脚本1 body: click_num=<1~9>   脚本2: 无 body
        这里采用脚本1 的随机 click_num, 兼容性更好。
        """
        url = BASE_URL + PATH_DRAW
        body = {"click_num": click_num} if click_num is not None else None
        resp = self.session.post(url, data=body, timeout=REQUEST_TIMEOUT)
        return self._parse(resp.text)

    # ---- 流程编排 (对应 JS all()) ----
    def run(self) -> AccountResult:
        remark = self.account.remark or self.account.token[:8]
        result = AccountResult(remark=remark)
        try:
            # 0. 先检测认证是否有效 (无效则直接返回, 不浪费后续请求)
            info_check = self.get_user_info()
            if self._is_auth_invalid(info_check):
                result.error = f"账户认证无效: {self._msg(info_check) or 'token/sign 已失效, 请重新抓包'}"
                self.log(f"  [{remark}] {result.error}")
                return result

            # 1. 签到前积分
            result.user_info_before = self._fmt_points(info_check, "查询失败")
            self.log(f"  [{remark}] 签到前: {result.user_info_before}")
            self._sleep_random()

            # 2. 签到
            sign_resp = self.sign()
            result.sign_msg = self._fmt_sign(sign_resp)
            self.log(f"  [{remark}] 签到: {result.sign_msg}")
            self._sleep_random()

            # 3. 抽奖 x2 (随机不重复 click_num, 对应脚本1)
            nums = random.sample(range(1, 10), 2)
            for n in nums:
                draw_resp = self.draw(n)
                msg = self._fmt_draw(draw_resp)
                result.draw_msgs.append(msg)
                self.log(f"  [{remark}] 抽奖(click_num={n}): {msg}")
                self._sleep_random()

            # 4. 签到后积分
            info_after = self.get_user_info()
            result.user_info_after = self._fmt_points(info_after, "查询失败")
            self.log(f"  [{remark}] 签到后: {result.user_info_after}")

        except requests.RequestException as e:
            result.error = f"网络异常: {e}"
        except Exception as e:  # noqa: BLE001
            result.error = f"未知异常: {e}"
        return result

    # ---- 响应解析 (与 JS 行为对齐) ----
    @staticmethod
    def _msg(d: dict[str, Any]) -> str:
        return d.get("message") or d.get("msg") or ""

    @classmethod
    def _is_auth_invalid(cls, d: dict[str, Any]) -> bool:
        """检测响应是否表明认证失效 (token/sign 无效或过期)。

        判断依据 (满足任一即视为认证无效):
          1. status 为 False 且 message 含认证失败关键词
          2. status 为 False 且响应中无 id / modou 等用户字段
        """
        if d.get("status") is False:
            msg = (cls._msg(d) or "").lower()
            # 常见的认证失败关键词
            auth_keywords = [
                "token", "登录", "登陆", "无效", "过期", "未授权",
                "unauthorized", "expire", "login", "请先", "身份",
            ]
            if any(kw in msg for kw in auth_keywords):
                return True
            # status 为 False 且无用户标识字段, 也视为认证无效
            data = d.get("data") if isinstance(d.get("data"), dict) else d
            if d.get("id") is None and data.get("id") is None and data.get("modou") is None:
                return True
        return False

    @classmethod
    def _fmt_points(cls, d: dict[str, Any], fail_text: str) -> str:
        if d.get("status") is False:
            return f"{fail_text}: {cls._msg(d) or '未知'}"
        data = d.get("data") if isinstance(d.get("data"), dict) else d
        has_user = d.get("id") is not None or data.get("id") is not None or data.get("modou") is not None
        if not has_user:
            return f"{fail_text}: {cls._msg(d) or '未知'}"
        points = data.get("modou") if data.get("modou") is not None else data.get("points", 0)
        return f"积分 {points}"

    @classmethod
    def _fmt_sign(cls, d: dict[str, Any]) -> str:
        if d.get("status") is False:
            return f"失败: {cls._msg(d) or '未知'}"
        if d.get("id") is not None:
            data = d.get("data") if isinstance(d.get("data"), dict) else d
            points = data.get("modou") if data.get("modou") is not None else d.get("modou", 0)
            return f"成功, 积分 {points}" if points else "成功"
        return f"失败: {cls._msg(d) or '未知'}"

    @classmethod
    def _fmt_draw(cls, d: dict[str, Any]) -> str:
        if d.get("status") is False:
            return f"失败: {cls._msg(d) or '未知'}"
        if d.get("id") is not None:
            # 脚本2 用 winning_desc 显示中奖描述
            desc = d.get("winning_desc") or (d.get("data") or {}).get("winning_desc") or "成功"
            return str(desc)
        return f"失败: {cls._msg(d) or '未知'}"


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------
def _validate_credential(name: str, value: str, account_label: str) -> str:
    """校验 token / sign 是否合法 (非空 + 纯 ASCII + 去除首尾空白)。
    requests 用 latin-1 编码 HTTP header, 含中文等非 ASCII 字符会直接抛错,
    这里提前给出友好提示。同时去除首尾空白, 避免复制 token 时误带空格。
    """
    if not value:
        return value
    # 去除首尾空白 (避免青龙/配置文件复制时误带空格导致 header 非法)
    value = value.strip()
    if not value:
        return value
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as e:
        raise ValueError(
            f"账号 [{account_label}] 的 {name} 含非 ASCII 字符 (位置 {e.start}-{e.end-1}), "
            f"请确认填的是抓包到的真实 {name}, 而不是 config.example.json 里的占位符。"
        )
    return value


def _load_env_indexed_accounts() -> list[Account]:
    """从环境变量 CITYBOX_ACCOUNTS_TOKEN{n} / SIGN{n} / REMARK{n} 加载账号。

    扫描规则:
      - 扫描序号 1 ~ MAX_ENV_INDEX (默认 100), 收集所有存在的 TOKEN{n}
      - 不要求连续, 允许跳号 (例如只设 TOKEN2 不设 TOKEN1, 用于临时禁用某账号)
      - SIGN 和 REMARK 同序号可选
      - 按序号从小到大排序返回
    """
    max_index = int(os.environ.get("CITYBOX_ACCOUNTS_MAX_INDEX", "100"))
    accounts: list[Account] = []
    for n in range(1, max_index + 1):
        token = os.environ.get(f"CITYBOX_ACCOUNTS_TOKEN{n}")
        if not token:
            continue  # 跳过缺失的序号, 继续扫描下一个
        sign = os.environ.get(f"CITYBOX_ACCOUNTS_SIGN{n}", "")
        remark = os.environ.get(f"CITYBOX_ACCOUNTS_REMARK{n}") or f"env{n}"
        _validate_credential("token", token, remark)
        _validate_credential("sign", sign, remark)
        accounts.append(Account(token=token, sign=sign, remark=remark))
    return accounts


def load_accounts(
    config_path: str | None,
    cli_token: str | None,
    cli_sign: str | None,
) -> list[Account]:
    """按优先级合并: 命令行 > 配置文件 > 编号环境变量 > JSON 数组环境变量。"""
    accounts: list[Account] = []

    # 1. 命令行单账号
    if cli_token:
        _validate_credential("token", cli_token, "cli")
        _validate_credential("sign", cli_sign or "", "cli")
        accounts.append(Account(token=cli_token, sign=cli_sign or "", remark="cli"))

    # 2. 配置文件
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        raw = cfg.get("accounts") if isinstance(cfg, dict) else cfg
        if not isinstance(raw, list):
            raise ValueError(f"配置文件 {config_path} 缺少 accounts 数组")
        for i, item in enumerate(raw):
            label = item.get("remark", f"acc{i+1}") if isinstance(item, dict) else f"acc{i+1}"
            if not isinstance(item, dict) or not item.get("token"):
                raise ValueError(f"配置文件第 {i+1} 个账号 [{label}] 缺少 token")
            token = _validate_credential("token", item["token"], label)
            sign = _validate_credential("sign", item.get("sign", ""), label)
            accounts.append(Account(
                token=token,
                sign=sign,
                remark=item.get("remark", f"acc{i+1}"),
                extra_headers=item.get("extra_headers", {}),
            ))

    # 3. 编号环境变量 CITYBOX_ACCOUNTS_TOKEN1/SIGN1/REMARK1 (推荐, 适合 cron / Docker)
    if not accounts:
        accounts = _load_env_indexed_accounts()

    # 4. JSON 数组环境变量 CITYBOX_ACCOUNTS (兼容旧方式)
    if not accounts:
        env_raw = os.environ.get("CITYBOX_ACCOUNTS")
        if env_raw:
            try:
                arr = json.loads(env_raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"环境变量 CITYBOX_ACCOUNTS 不是合法 JSON: {e}")
            if not isinstance(arr, list):
                raise ValueError("环境变量 CITYBOX_ACCOUNTS 必须是 JSON 数组")
            for i, item in enumerate(arr):
                label = item.get("remark", f"env{i+1}") if isinstance(item, dict) else f"env{i+1}"
                if not isinstance(item, dict) or not item.get("token"):
                    raise ValueError(f"环境变量第 {i+1} 个账号 [{label}] 缺少 token")
                token = _validate_credential("token", item["token"], label)
                sign = _validate_credential("sign", item.get("sign", ""), label)
                accounts.append(Account(
                    token=token,
                    sign=sign,
                    remark=item.get("remark", f"env{i+1}"),
                    extra_headers=item.get("extra_headers", {}),
                ))

    if not accounts:
        raise ValueError(
            "未找到任何账号配置。请通过以下任一方式提供账号:\n"
            "  - 命令行: --token / --sign\n"
            "  - 配置文件: --config config.json\n"
            "  - 编号环境变量: CITYBOX_ACCOUNTS_TOKEN1 / SIGN1 / REMARK1 (推荐)\n"
            "  - JSON 数组环境变量: CITYBOX_ACCOUNTS"
        )
    return accounts


# ---------------------------------------------------------------------------
# 通知 (可选, 默认只打印)
# ---------------------------------------------------------------------------
def notify(summary: str, webhook: str | None, pushplus_token: str | None = None,
           pushplus_topic: str | None = None, pushplus_template: str = "txt") -> None:
    """通知推送; 失败不影响主流程。

    支持两种方式 (可同时用):
      1. 通用 webhook: --webhook URL, POST JSON {text: summary}
      2. PushPlus 群组: --pp-token <token> [--pp-topic <群组编码>]
         参考 https://pushplus.plus/doc/guide/api.html
         不填 topic 则仅发给自己; 填 topic 则发给该群组所有成员 (一对多)。
    """
    # 1. 通用 webhook
    if webhook:
        try:
            requests.post(webhook, json={"text": summary}, timeout=10)
        except Exception as e:  # noqa: BLE001
            print(f"[notify] webhook 推送失败: {e}", flush=True)

    # 2. PushPlus
    if pushplus_token:
        url = "http://www.pushplus.plus/send"
        payload = {
            "token": pushplus_token,
            "title": "CITYBOX 魔盒签到结果",
            "content": summary,
            "template": pushplus_template,
        }
        if pushplus_topic:
            payload["topic"] = pushplus_topic
        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("code") == 200:
                target = f"群组 [{pushplus_topic}]" if pushplus_topic else "自己"
                print(f"[notify] PushPlus 推送已提交 -> {target} (流水号: {data.get('data')})", flush=True)
            else:
                print(f"[notify] PushPlus 推送失败: {data.get('msg')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[notify] PushPlus 推送异常: {e}", flush=True)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CITYBOX 魔盒 微信小程序签到 Python 版"
    )
    parser.add_argument("--config", help="配置文件路径 (JSON)")
    parser.add_argument("--token", help="单账号 token (命令行直传)")
    parser.add_argument("--sign", help="单账号 sign (命令行直传)")
    parser.add_argument(
        "--webhook",
        default=os.environ.get("SIGNHUB_WEBHOOK_URL"),
        help="可选通知 webhook (POST JSON {text:...}); 环境变量 SIGNHUB_WEBHOOK_URL",
    )
    parser.add_argument(
        "--pp-token",
        default=os.environ.get("SIGNHUB_PUSHPLUS_TOKEN"),
        help="PushPlus token (一对多推送); 环境变量 SIGNHUB_PUSHPLUS_TOKEN; 参考 https://pushplus.plus/doc/guide/api.html",
    )
    parser.add_argument(
        "--pp-topic",
        default=os.environ.get("SIGNHUB_PUSHPLUS_TOPIC"),
        help="PushPlus 群组编码, 不填仅发给自己; 填则发给该群组所有成员; 环境变量 SIGNHUB_PUSHPLUS_TOPIC",
    )
    parser.add_argument(
        "--pp-template",
        default=os.environ.get("SIGNHUB_PUSHPLUS_TEMPLATE", "txt"),
        help="PushPlus 模板: txt/html/markdown/json (默认 txt); 环境变量 SIGNHUB_PUSHPLUS_TEMPLATE",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="禁用 SSL 证书校验 (解决 Fiddler/Charles 代理或证书缺失导致的 SSL 错误)",
    )
    parser.add_argument(
        "--proxy",
        help="自定义代理, 例如 http://127.0.0.1:8888 (走 Fiddler 时使用)",
    )
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="读取系统代理环境变量 (HTTP_PROXY/HTTPS_PROXY), 默认关闭",
    )
    args = parser.parse_args(argv)

    accounts = load_accounts(args.config, args.token, args.sign)

    options = ClientOptions(
        verify_ssl=not args.no_verify_ssl,
        proxy=args.proxy,
        trust_env=args.trust_env,
    )
    # 友好提示
    if not options.verify_ssl:
        print("[WARN] 已禁用 SSL 证书校验, 仅建议在本地调试 (Fiddler/Charles) 时使用", flush=True)
    if options.proxy:
        print(f"[INFO] 使用代理: {options.proxy}", flush=True)
    if not options.trust_env and not options.proxy:
        print("[INFO] 已忽略系统代理 (避免 Fiddler 残留配置干扰), 如需走系统代理请加 --trust-env", flush=True)

    print(f"========== CITYBOX 魔盒签到开始, 共 {len(accounts)} 个账号 ==========", flush=True)
    summaries: list[str] = []
    for idx, acc in enumerate(accounts, 1):
        print(f"\n----- [{idx}/{len(accounts)}] {acc.remark or acc.token[:8]} -----", flush=True)
        client = CityBoxClient(acc, options=options)
        result = client.run()
        s = result.summary()
        summaries.append(s)
        print(s, flush=True)
        # 账号之间也随机延时, 避免风控
        if idx < len(accounts):
            time.sleep(random.uniform(2.0, 5.0))

    final = "\n\n".join(summaries)
    print("\n========== 全部完成 ==========\n" + final, flush=True)
    notify(
        final,
        webhook=args.webhook,
        pushplus_token=args.pp_token,
        pushplus_topic=args.pp_topic,
        pushplus_template=args.pp_template,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
