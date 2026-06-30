# CITYBOX 魔盒签到

将 GitHub 上两个 CITYBOX 魔盒微信小程序签到 JS 脚本合并转换为 Python 版本。

- 来源 1: <https://github.com/FboZhu/QX/blob/main/js/MH_CityBox.js>
- 来源 2: <https://github.com/axtyet/Luminous/blob/main/cyz_13724/他人仓库/chavyleung-scripts/citybox/citybox.js>

## 登录信息是怎么传入的

CITYBOX 魔盒是微信小程序, 登录态完全靠 HTTP 请求头里的两个字段:

| 字段 | 位置 | 说明 |
|------|------|------|
| `token` | 请求头 | 用户身份令牌, 必填 |
| `sign`  | 请求头 | API 签名, 部分接口需要 |

> 两个 JS 脚本都依赖抓包小程序的请求来拿到这两个字段。
> 脚本1 (FboZhu) 用 MITM 重写 `get_user_info` 响应自动抓取并写入 `MHCityBoxCookies`;
> 脚本2 (axtyet) 用整份 HAR headers, 存入 `boxapp_citybox_har`。
> 本 Python 版本直接复用 `token` + `sign` 字段, 用户抓包后填入即可。

## 抓包教程 (获取 token / sign)

1. 电脑安装 Charles / Fiddler / Proxyman / Stream, 手机配置代理并信任证书 (iOS 还需在 *设置 → 通用 → 关于本机 → 证书信任设置* 启用)。
2. 手机微信打开 CITYBOX 魔盒小程序, 进入"我的"页面。
3. 在抓包工具中找到 `https://api.icitybox.cn/api/user/get_user_info` 这条请求。
4. 复制请求头里的 `token` 和 `sign` 两个值。

## 安装

```bash
pip install requests
```

## 使用

### 方式 A: 配置文件 (推荐, 支持多账号)

```bash
cd citybox
cp config.example.json config.json
# 编辑 config.json 填入 token / sign
python sign.py --config config.json
```

### 方式 B: 环境变量 (适合 cron / Docker, 推荐用编号方式)

```bash
# 编号方式 (推荐, 无需写 JSON)
# Windows
set CITYBOX_ACCOUNTS_TOKEN1=xxx
set CITYBOX_ACCOUNTS_SIGN1=yyy
set CITYBOX_ACCOUNTS_REMARK1=主号
set CITYBOX_ACCOUNTS_TOKEN2=aaa
set CITYBOX_ACCOUNTS_SIGN2=bbb
set CITYBOX_ACCOUNTS_REMARK2=小号
python sign.py

# Linux / macOS
export CITYBOX_ACCOUNTS_TOKEN1=xxx
export CITYBOX_ACCOUNTS_SIGN1=yyy
export CITYBOX_ACCOUNTS_REMARK1=主号
python sign.py

# 或 JSON 数组方式 (兼容旧版)
set CITYBOX_ACCOUNTS=[{"token":"xxx","sign":"yyy","remark":"main"}]
python sign.py
```

编号环境变量规则:

| 字段 | 必填 | 默认 |
|------|------|------|
| `CITYBOX_ACCOUNTS_TOKEN{n}` | 是 | — |
| `CITYBOX_ACCOUNTS_SIGN{n}` | 否 | 空 |
| `CITYBOX_ACCOUNTS_REMARK{n}` | 否 | `env{n}` |

- `{n}` 从 1 开始递增
- 遇到缺失的 `TOKEN{n}` 立即停止扫描 (避免空洞, 如设了 1、2、4 只加载 1、2)
- SIGN 和 REMARK 同序号可选

### 方式 C: 命令行单账号

```bash
python sign.py --token xxxx --sign yyyy
```

### Fiddler 代理调试

```bash
# Fiddler 开着时, 跳过 SSL 校验
python sign.py --config config.json --no-verify-ssl

# 显式走 Fiddler 代理
python sign.py --config config.json --proxy http://127.0.0.1:8888 --no-verify-ssl
```

## 通知推送 (可选, 命令行参数和环境变量二选一, 命令行优先)

### 通用 webhook

```bash
python sign.py --config config.json --webhook https://your.webhook/url
# 或
set SIGNHUB_WEBHOOK_URL=https://your.webhook/url
python sign.py --config config.json
```

会以 `{"text": "..."}` POST 推送运行结果 (兼容飞书 / 钉钉 / 自建 webhook)。

### PushPlus 一对多群组推送

参考 [PushPlus 官方文档](https://pushplus.plus/doc/guide/api.html)。

```bash
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
```

环境变量对照表:

| 命令行选项 | 环境变量 | 默认 |
|------|------|------|
| `--webhook` | `SIGNHUB_WEBHOOK_URL` | 无 |
| `--pp-token` | `SIGNHUB_PUSHPLUS_TOKEN` | 无 |
| `--pp-topic` | `SIGNHUB_PUSHPLUS_TOPIC` | 无 (发给自己) |
| `--pp-template` | `SIGNHUB_PUSHPLUS_TEMPLATE` | txt |

## 青龙面板集成

### 拉取仓库

青龙面板 → 订阅管理 → 新建订阅, 或在容器内执行:

```bash
ql repo https://github.com/ui-beam-9/sign-hub.git "citybox" "" "" "main"
```

### 环境变量配置

| 名称 | 必填 | 说明 |
|------|------|------|
| `CITYBOX_ACCOUNTS_TOKEN1` | 是 | 账号1的 token |
| `CITYBOX_ACCOUNTS_SIGN1` | 否 | 账号1的 sign |
| `CITYBOX_ACCOUNTS_REMARK1` | 否 | 账号1的备注 (默认 env1) |
| `CITYBOX_ACCOUNTS_TOKEN2` | 否 | 账号2的 token (允许多账号, 序号可跳) |
| `SIGNHUB_PUSHPLUS_TOKEN` | 否 | PushPlus token |
| `SIGNHUB_PUSHPLUS_TOPIC` | 否 | PushPlus 群组编码 (不填发给自己) |
| `SIGNHUB_PUSHPLUS_TEMPLATE` | 否 | PushPlus 模板 (默认 txt) |
| `SIGNHUB_WEBHOOK_URL` | 否 | 通用 webhook URL |

> 编号环境变量允许跳号, 例如只设 `TOKEN2` 不设 `TOKEN1` (用于临时禁用账号1), 脚本会扫描 1~100 收集所有存在的账号。
> 可通过 `CITYBOX_ACCOUNTS_MAX_INDEX` 调整扫描上限 (默认 100)。

### 定时任务

青龙拉取后, 在定时任务中新建:
- 命令: `task citybox/sign.py`
- 定时规则: `39 11 * * *` (每天 11:39) 或按需调整

## 定时运行 (cron 示例)

```bash
# 每天 11:39 执行 (对应原 JS 脚本的 cron: 39 11 * * *)
39 11 * * * /usr/bin/python3 /path/to/sign-hub/citybox/sign.py --config /path/to/sign-hub/citybox/config.json >> /var/log/citybox.log 2>&1
```

Windows 计划任务可在 *任务计划程序* 中新建, 程序填 `python.exe`, 参数填 `sign.py --config config.json`, 起始位置填 `citybox` 目录。

## 智能流程

每个账号执行时按以下顺序判断:

```
1. 认证检测 (get_user_info)
   ├─ 认证无效 (token/sign 失效) → 标记错误, 跳过签到抽奖, 仍发通知
   └─ 认证有效 → 继续

2. 签到 (up_sign)
   ├─ 今日已签到 → 跳过抽奖, 继续下一个账号
   └─ 签到成功 → 继续抽奖

3. 抽奖 x2 (draw_results)
   └─ 随机 click_num 1~9, 两次不重复

4. 签到后积分查询
```

特点:
- **认证失效自动跳过**: token/sign 过期不会浪费后续签到/抽奖请求, 但会通过通知告知"账户认证无效"
- **已签到自动跳过抽奖**: 避免重复请求触发风控
- **token 自动去首尾空白**: 避免青龙面板复制 token 误带空格导致 header 非法
- **不管成功失败都发通知**: 只要配置了 webhook / PushPlus, 都会发送结果

## API 流程 (与 JS 脚本对照)

| 步骤 | JS 函数 | Python 方法 | 接口 |
|------|---------|-------------|------|
| 1 | `UserInfo("before")` | `client.get_user_info()` | GET `/api/user/get_user_info` |
| 2 | `CityBoxSign()` | `client.sign()` | GET `/api/user/up_sign?ts=<ms>` |
| 3 | `DrawResults(0, n)` x2 | `client.draw(n)` | POST `/api/roulette_draw/draw_results`, body `click_num=n` |
| 4 | `UserInfo("after")` | `client.get_user_info()` | GET `/api/user/get_user_info` |

接口之间随机延时 2~5 秒, 账号之间随机延时 2~5 秒, 与 JS 脚本1 一致。

## 验收

```bash
cd citybox

# 1. 语法检查
python -m py_compile sign.py

# 2. 帮助信息
python sign.py --help

# 3. 单账号实跑 (需真实 token)
python sign.py --token <你的token> --sign <你的sign>
```

实测结果: 主号签到前 117 → 签到后 182 积分 (+65, 含抽奖 40+20) ✅

## 风险与免责

- 本脚本仅供学习交流, 请勿用于商业用途。
- 频繁请求可能触发服务端风控, 默认 2~5 秒随机延时, 可自行调整。
- token / sign 会过期, 失效后需重新抓包。
- 作者不对使用本脚本造成的任何账号风险负责。
