# our-wardrobe

**收好每一件，留给下一次心动**

两个人的衣柜：人用网页，小机用 MCP，共用物品、照片、短备注、批注与抽挑记录。名字、分类和抽一套规则都能改。默认空柜，没有真实物品、图片、密钥或聊天平台依赖。

网页保留珍珠浅色底、宋体风格、双人柜子切换、六格抽取、物品网格、卡片背面与底部挑选栏。另有林间蝶、青苹果配色。字体只使用 CSS 回退，不捆绑字体或背景图片。结果卡是奶油底、酒红边框，最多八格，指令格直接写正文。

## 我家小机能用吗

**能接 MCP 就能用**：本机接 stdio，只能填远程地址的客户端接 Streamable HTTP。名字、角色和分类都由衣柜配置决定。

- **能往聊天塞消息 → 递便签**：把两个 webhook 接到自己的消息入口，卡片发进聊天，再单独给小机递通知。
- **塞不了消息 → 小机自己翻**：保留 MCP，让小机在对话开始或人说“抽好了”时查未读。官方或封闭前端也可走这条路；不要求前端开放消息注入。

可粘贴到项目说明 / 自定义指令：

> 每次对话开头，或我说“抽好了”“挑好了”时，先调用 wardrobe_unread 查看衣柜未读记录，包括我给自己和给你抽的。读完物品和附言，需要看图时用 wardrobe_view 或 wardrobe_card；只把实际看过的记录 id 交给 wardrobe_mark_read。还有 remaining 就继续查。没有未读就正常聊天，不要为了检查而重新抽取。我找不到入口时，调用 wardrobe_link，把“打开衣柜”链接发给我。

### 已实测（2026-11-25）

- 本机 stdio MCP（Claude Code）
- 公网 Streamable HTTP：Claude 官方 API 的 MCP 连接器（`mcp_servers` + `mcp_toolset`）
- 公网 Streamable HTTP：Aru（iOS），登录方式选「无需登录」，地址直接填 `/mcp/<密钥>`

其他前端理论上能填远程 MCP 地址就能用，没测过的不打包票。接通或接不通，欢迎在 Issues 里说一声。

## 快速开始

需要 Python 3.10+。Linux / macOS：

```bash
cd our-wardrobe
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.json config.local.json
export WARDROBE_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m wardrobe
```

浏览器打开 `http://127.0.0.1:8765`，输入同一个密钥。服务默认仅监听本机；可用 `python -m wardrobe --host 0.0.0.0 --port 8765` 改监听。外网使用请在前面接 HTTPS 反向代理。停止后备份整个 `data/`，其中包含 SQLite 和照片、卡片。

密钥无默认值，请自己保存，不要提交到仓库。网页将它保存在当前 origin 的 localStorage，“锁上衣柜”会清除。API、物品图和卡片图均用 Bearer 请求头认证，URL 不携带密钥。两位角色共用一个密钥，是合作使用的身份标记，不是彼此隔离的账号。

想先试试，可在另一个终端激活虚拟环境并设置**同一个**密钥，执行：

```bash
python scripts/seed.py
```

这会添加五件虚构无图衣物；重复执行跳过同角色、分类、名称的现有物品。改过角色或分类 id 后，也要改 `examples/items.json`，或用 `--file 自己的示例.json`。

详细教程：[教小机装衣柜](docs/教小机装衣柜.md)。

## 怎么用

- 切换“我的 / 小机的”柜子，按分类筛选；点卡片看详情、短备注、批注、次数和最近使用记录。
- “放进柜子”添加名字、分类、所有者和可选照片；“修改这件”可改以上字段。指令必须写正文，最多 200 字，不能放图片。其他短备注最多 500 字。
- 批注写在详情的“卡片背面”，每条有作者、创建时间，修改后保留修改时间。网页只能改删网页角色自己的批注，删除前确认；MCP 同样按作者检查。
- “抽一套”按目标的套装分类抽取；点击后仅为 max_count>1 的套装格子显示数量选择（默认只有玩具），确认后抽取。普通数量框默认隐藏，勾哪格才显示哪格；单格可选数量，勾多格时固定每格一件。
- 勾选物品后，“挑这几件”直接选定 1–8 件；也可先圈更多候选，再选抽几件，点“从这几件里抽”，不重复抽取，最多八件。
- 底部“附一句话”只跟随本次卡片，最多 40 字；它不会写进物品批注。
- 每次成功生成抽挑记录都会累加次数并更新最近使用时间。详情编辑里的“使用记录 · 手动校正”可调整次数、时间；手动校正不生成抽卡历史。
- “抽取记录”可看当时物品快照、双方名字、附言、卡片，以及发卡片 / 通知小机两个结果。编辑、移除物品不会改写旧记录。

空格跳过；某格数量不够时取已有的；全空返回 409。总计超过八件时拒绝整次操作，不会悄悄截掉物品或计次。候选池不足请求数量时返回 422。

## 默认分类与配置

修改 `config.local.json` 后重启服务。

| 分类 id | 显示名 / 动作 | 可以拥有 | 默认抽一套 | 单格 / 套装每格上限 |
| --- | --- | --- | --- | --- |
| clothes | 衣服 / 穿 | 双方 | 双方 | 1 |
| stockings | 袜子 / 穿 | 人 | 人 | 1 |
| accessory | 饰品 / 戴 | 双方 | 双方 | 1 |
| toy | 玩具 / 用 | 双方 | 双方 | 3 |
| medicine | 药品 / 吃 | 双方 | 小机 | 1 |
| order | 指令 / 做 | 双方 | 小机 | 1 |

默认角色是 `human`（我）、`ai`（小机）。两位的 id 和显示名都在 `roles`；`clients.web` 指定人类默认发起人，`clients.mcp` 指定小机默认发起人，两者必须不同。每次操作仍独立记录 `chosen_by` 和 `target`，人给自己抽也会通知小机。

| 配置项 | 含义 |
| --- | --- |
| title | 网页标题，默认“我们的衣柜” |
| roles | 恰好两位角色：id、name |
| clients | web / mcp 默认身份，引用角色 id |
| categories | 最多 40 类，可删到空数组 |
| font_path | 可选卡片字体路径，相对路径基于配置文件目录 |
| public_base_url | 外部接收端能访问的衣柜 origin，不含子路径 |
| webhook_url | “发卡片”钩子，所有抽挑都会调用；空字符串关闭 |
| notify_webhook_url | “通知小机”独立钩子，所有人发起的抽挑调用；空字符串关闭 |

每个分类包含 `id`、`name`、`owners`、`action`、`in_outfit`、`max_count`、`text_only`。`in_outfit` 可为 true / false（所有可拥有角色都参加 / 不参加），也可为角色 id 数组；`max_count` 是单格及套装每格数量上限，1–8，默认 1；`text_only` 默认 false，true 表示必须填写正文且不接受图片。

例如新增帽子格：

```json
{"id":"hats","name":"帽子","owners":["human","ai"],"action":"戴","in_outfit":false,"max_count":1,"text_only":false}
```

删分类后旧物品仍可查看、编辑到其他分类或移出，不再参与抽挑；历史保留。改显示名后新记录用新名字，旧记录保留当时名字。角色 id 建议首次使用前定好；已有数据不会自动改写 id，改动时需同步 `owners`、`in_outfit` 数组、`clients` 并自行迁移数据。

首次版本数据库会自动补上 `last_used_at`、批注修改时间和已读表，保留已有内容与次数。旧物品分类不会自动映射为六格，可在网页修改或保留旧分类配置。

## 环境变量和图片

| 变量 | 默认值 / 用途 |
| --- | --- |
| WARDROBE_API_KEY | 必填；网页、HTTP API 和 stdio MCP 共用 |
| WARDROBE_MCP_KEY | 默认空，关闭远程 MCP；开启时用独立的至少 32 位 URL 安全随机密钥 |
| PUBLIC_URL | 网页公开 origin（如 https://wardrobe.example.org），覆盖 public_base_url；入口与媒体地址都使用它 |
| WARDROBE_CONFIG | 优先 config.local.json，否则 config.json；显式路径不存在时报错 |
| WARDROBE_DATA_DIR | 项目下 data/；数据库与图片 |
| WARDROBE_URL | MCP / seed 使用的服务地址，默认 http://127.0.0.1:8765 |

照片最多 5 MB、2000 万像素，支持 JPG / PNG / WebP / GIF；GIF 用首帧，统一规范化为 JPEG，不保留原元数据。旧图片为历史快照保留，不随物品删除立即清理。

卡片优先使用配置字体，其次系统 Noto Serif CJK / Noto Sans CJK / 文泉驿，再回退到通用字体。没有中文字形时，PNG 中文可能显示方框，网页和 JSON 文字仍可用。可安装有适当授权的 Noto CJK 字体，或设置 `font_path`；分发字体时需附相应许可证。本仓库不打包字体。

## 踩坑笔记：卡片发出去了，小机却看不见

聊天桥常会过滤小机自己发的消息。如果衣柜卡片以小机名义进入聊天，人在网页给自己或给小机抽挑时，卡片虽然出现在聊天里，桥却可能不会再把它递给小机。**发卡片成功不等于小机已经知道。**

这里提供两条路，可以同时使用：

1. **Webhook 推送**：`webhook_url` 专门发卡片进聊天；`notify_webhook_url` 单独把这次抽挑递给小机。接收通知的一端应调用自己的模型消息入口或唤醒入口，不要再次伪装成小机自己的发言。人发起的抽、挑、候选池抽取，无论 target 是谁都通知。一个钩子失败也会继续尝试另一个。
2. **小机主动查询**：不接 webhook 也能调用 `wardrobe_unread()`，读取人发起的未读抽挑，必要时用 `wardrobe_card(record_id=...)` 看卡片，再调用 `wardrobe_mark_read(record_ids=[...])` 标记看过的记录。可以在每次对话开始时检查；MCP 本身不会主动唤醒模型。查询不自动标已读，投递成功也不自动标已读，避免漏读。

两个钩子都先保存卡片、历史和计次，再各自 POST JSON；发卡片事件为 `wardrobe.selection`，通知事件为 `wardrobe.notify`。payload 包含：

```json
{
  "event": "wardrobe.notify",
  "id": "唯一记录标识",
  "mode": "pick",
  "chosen_by": "human",
  "chosen_by_name": "我",
  "target": "ai",
  "target_name": "小机",
  "text": "我 为 小机挑选：穿白衬衫。今天这样搭\n打开衣柜：https://wardrobe.example.org/",
  "line": "今天这样搭",
  "items": [],
  "card_url": "https://wardrobe.example.org/api/media/卡片文件名.png",
  "wardrobe_url": "https://wardrobe.example.org/",
  "created_at": "2026-01-01T00:00:00+00:00",
  "webhook": {"status":"disabled"},
  "notification": {"status":"pending"}
}
```

每次新卡片的 PNG 页脚印有入口地址，`text` 自带“打开衣柜”文字链接，`wardrobe_url` 供接收端渲染成可点击按钮（PNG 本身不能点击）。网页结果和历史也提供入口链接。旧历史快照保持原样。实际 `items` 是完整快照，含分类、动作、短备注、指令正文和图片地址。接收端按 `event + id` 去重；两个钩子指向同一服务时也不会相互吞掉。payload 不含密钥，图片地址不是公开分享链接；接收端需自行配置同一个衣柜密钥，用 Bearer 请求头取图。

每个钩子超时 5 秒、不跟随重定向、不自动重发、不转发衣柜密钥。2xx 是 `delivered`，非 2xx 是 `failed`，网络异常是 `unknown`，未接入是 `disabled`，进程中断可能留下 `pending`。小机发起的记录不需通知自己，通知状态为 `not_applicable`。2xx 只表示接收端接受，并不证明模型读过；读过后仍可调用标已读工具。任何投递失败都不会撤销抽挑。

## MCP 工具

```bash
python -m pip install -r requirements-mcp.txt
python wardrobe_mcp.py
```

通常由 MCP 客户端启动 stdio 进程，HTTP 服务需另行保持运行。先调用 `wardrobe_config`，使用实际角色和分类 id；工具默认作者取 `clients.mcp`，可显式指定，target 必须明确。

| 工具 | 能力 |
| --- | --- |
| wardrobe_link | 取得“打开衣柜”的网页链接，不含任何密钥 |
| wardrobe_config / wardrobe_list | 读配置、按 owner / category 列物品 |
| wardrobe_view | 读详情、短备注、批注、次数、最近使用；有图返回 ImageContent 图片本身 |
| wardrobe_add | 给任一方添加物品，image_path 读取 MCP 机器的本地照片 |
| wardrobe_edit | 改名、描述、所有者、分类、图片及使用次数 / 时间 |
| wardrobe_remove | 移出物品，保留历史 |
| wardrobe_note | 添加带作者与时间的批注 |
| wardrobe_note_edit / wardrobe_note_delete | 改 / 删自己的批注；删除先确认，再传 confirm=true |
| wardrobe_draw | 套装、单格、混抽、候选池；支持 counts 按格件数 |
| wardrobe_pick | 手挑 1–8 件，可附一句话 |
| wardrobe_history / wardrobe_card | 分页历史 / 返回卡片图片本身 |
| wardrobe_unread / wardrobe_mark_read | 查人发起的未读抽挑 / 看完标已读 |

`wardrobe_edit(description="")` 清空短备注（指令不允许空正文）；`remove_image=true` 移除图片；`clear_last_used_at=true` 清空最近使用时间。stdio 的图片路径属于 MCP 运行机器，不能直接填写浏览器电脑上的路径。远程 MCP 的 `image_path` 仅能读取 `WARDROBE_DATA_DIR/mcp-imports/` 内的图片（默认 `data/mcp-imports/`）；先由管理员放入文件，再传相对文件名如 `shirt.png`。两个传输的工具名称和参数一致，远程端不会任意读取服务器文件。

抽取参数示例见教程。`wardrobe_list` 的图片 URL 不代表小机看过图；看实物请用 `wardrobe_view`，不必先写描述。

## 公网 MCP：同一个服务，另一个密钥

安装 `requirements-mcp.txt`，保留网页密钥，再在**服务进程**环境设置：

```bash
export WARDROBE_MCP_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PUBLIC_URL="https://wardrobe.example.org"
python -m wardrobe --host 127.0.0.1 --port 8765
```

保存这次生成的密钥，重启时复用；不要每次启动都重新生成。它不能等于网页密钥。远程地址为 `https://wardrobe.example.org/mcp/<WARDROBE_MCP_KEY的值>`，不需要填写 Bearer 或 OAuth。未设置该变量就不挂载远程端点。支持 Streamable HTTP，和 stdio 共用全部 16 个工具。工具通过进程内 HTTP API 操作同一数据库，不需要另起 MCP 服务，也不依赖 WARDROBE_URL 或监听端口默认值。

### HTTPS 反代：Caddy

域名的 DNS 指向部署机器，允许公网访问 80/443，应用只监听本机。Caddyfile：

```caddyfile
wardrobe.example.org {
    reverse_proxy 127.0.0.1:8765
}
```

Caddy 为域名提供 HTTPS，并将路径原样转发。不要把 `/mcp` 前缀删掉，也不要给该路径加浏览器登录页。此例不启用访问日志。[Caddy 反代文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)

### HTTPS 隧道：Cloudflare Tunnel

域名由 Cloudflare 管理且已安装 cloudflared 时，可以不开放应用的入站端口：

```bash
cloudflared tunnel login
cloudflared tunnel create wardrobe
cloudflared tunnel route dns wardrobe wardrobe.example.org
```

在本机保存 `tunnel.yml`（替换 UUID 和凭据文件的绝对路径）：

```yaml
tunnel: YOUR-TUNNEL-UUID
credentials-file: /absolute/path/YOUR-TUNNEL-UUID.json
ingress:
  - hostname: wardrobe.example.org
    service: http://127.0.0.1:8765
  - service: http_status:404
```

```bash
cloudflared tunnel --config tunnel.yml run wardrobe
```

公网使用 HTTPS 地址，应用仍用本机 HTTP。`PUBLIC_URL` 保持 `https://wardrobe.example.org`；不要在 MCP 路径前加交互式 Access 登录或验证码。[Cloudflare 本地管理隧道指南](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/)

### 在 claude.ai 自定义连接器中填写

在 claude.ai 的设置 → Connectors（连接器）中添加自定义连接器，名称自定，服务器 URL 填上面完整的 `https://wardrobe.example.org/mcp/<密钥>`，包括路径。若出现可选 OAuth Client ID / Secret，留空；本服务使用路径密钥。完成添加后，在对话中启用该连接器，先请小机调用 `wardrobe_config` 与 `wardrobe_link`，再测试抽卡和未读。官方 App 使用同一账号的连接器；具体入口和可用性以账号界面为准。

连接来自云端，因此地址必须能被公网访问，使用标准 HTTPS 443；不能填写本机 localhost 或私网地址。[官方自定义连接器说明](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)

### 路径密钥的泄露风险

完整 MCP URL 就是凭据，获得它的人可读写整个衣柜。不要放进截图、聊天、公开文档、按钮、PUBLIC_URL 或提交文件。它可能出现在浏览器历史、代理 / CDN 访问日志和连接器诊断中；限制日志访问和保留时间，关闭或脱敏请求路径日志。`python -m wardrobe` 默认关闭 Uvicorn 访问日志，自行用 uvicorn 启动时加 `--no-access-log`。反代和隧道日志要单独检查，HTTPS 不能阻止服务端日志记录 URL。

泄露后生成新的 WARDROBE_MCP_KEY、重启服务、更新连接器；旧地址立即失效，网页密钥不受影响。独立密钥用于单独轮换，并不缩小远程 MCP 的衣柜读写权限。

## 找到衣柜：主屏幕和嵌入按钮

通过 HTTPS 打开网页，在手机浏览器菜单选择“添加到主屏幕”（iOS 通常在分享菜单），即可使用独立窗口入口。项目提供 manifest、自绘 SVG 和 180/192/512 PNG 图标，不使用外部素材。不同浏览器的菜单有所不同；这里提供在线入口，不提供离线读写，也不缓存私密数据供离线使用。

卡片和两个 webhook 的 `wardrobe_url`、MCP 的 `wardrobe_link()` 都指向 PUBLIC_URL。它只打开网页，仍需输入网页访问密钥。更换域名后新卡片使用新地址，已生成的历史卡片保留原地址。

可嵌入支持 HTML 的页面：

```html
<a href="https://wardrobe.example.org/" target="_blank" rel="noopener noreferrer">打开衣柜</a>
```

将域名换成 PUBLIC_URL，不要拼入网页或 MCP 密钥。链接适用于别的前端；整个网页不支持 iframe 嵌入。

## HTTP API

`/api/*` 均需 `Authorization: Bearer ...`，数据使用 JSON；`GET /api/link` 返回 `{label, url}`。`/`、`/static/*`、`/health` 公开；可选的 `/mcp/<密钥>` 单独验证路径密钥。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/config | 客户端配置，不返回钩子地址或字体路径 |
| GET / POST | /api/items | 列表 / 添加 |
| GET / PATCH / DELETE | /api/items/{id} | 详情 / 修改 / 移除 |
| POST | /api/items/{id}/notes | 添加批注：author、text |
| PATCH / DELETE | /api/items/{id}/notes/{note_id} | 修改：author、text；删除 JSON：author、confirm=true |
| POST | /api/draw | chosen_by、target，可带 mode、category、categories、counts、item_ids、count、line |
| POST | /api/pick | chosen_by、target、item_ids、line |
| GET | /api/history | target 筛选，limit 1–100、offset 分页 |
| GET | /api/unread | 人发起的未读记录，limit 1–100，含 remaining |
| POST | /api/unread/read | record_ids 数组；仅标记这些记录 |
| GET | /api/media/{filename} | 物品图 / 卡片图 |
| GET | /api/openapi.json | 完整请求字段和校验规则 |

添加必填 name、owner、category、added_by，可选 description 和纯 Base64 的 image_base64（不含 data URL 前缀）。PATCH 可传 remove_image、use_count、last_used_at（ISO 时间，null 清空）。

抽取默认 mode=outfit；单抽传 mode=single、category；混抽传 categories；套装和单格可传 counts。候选池只传 item_ids 和 count，不与 category、categories、counts 或 single 混用。

## 验证与常见问题

```bash
python -m pip install -r requirements-mcp.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke.py
# 可选浏览器端到端验证
python -m pip install playwright
python -m playwright install chromium
python tests/smoke.py --browser --artifacts /tmp/our-wardrobe-review
```

smoke 使用临时配置、临时数据库、端口 18765，结束后清理服务和数据；`--artifacts` 可保留合成截图。禁止 socket 的环境可运行：

```bash
WARDROBE_TEST_DIRECT=1 python -m unittest discover -s tests -p 'test_*.py' -v
node --check static/app.js
node tests/test_frontend.cjs
```

`test_round3.py` 另通过真实 ASGI middleware 和 MCP JSON-RPC 验证远程握手、16 工具参数一致、读写/看图、密钥隔离、Host/Origin 检查、入口和图标；在受限环境下测试定时唤醒事件循环，不替换应用或 MCP 实现。`tests/smoke.py` 已包含真实 HTTP、stdio 和远程 MCP SDK 客户端测试。

离线路由 / 进程内 ASGI 测试不等于真实网络、stdio 或浏览器验证。测试覆盖六格归属 / 套装规则、玩具数量、候选池、指令约束、八格上限、批注修改删除、双钩子和未读回执，以及原有认证、图片和历史快照。

- 401：网页、HTTP API、stdio MCP 必须用同一网页密钥；远程 MCP 使用独立路径密钥，错误地址返回 404。
- 超时：写入可能已完成，先查历史再决定是否重试，当前没有请求幂等键或 webhook 自动补发。
- 外部接收端看不到图：核对 PUBLIC_URL / public_base_url、可达性和 Bearer 请求头。
- 改配置没生效：重启服务，并检查 WARDROBE_CONFIG 是否覆盖本地文件。
- 卡片中文方框：安装中文字体或配置 font_path。
- MCP 找不到图片：确认路径在 MCP 机器上，且进程有读取权限。

实现入口：`wardrobe/app.py`（API / 数据库 / 钩子）、`wardrobe/config.py`（配置）、`wardrobe/cards.py`（卡片）、`static/`（网页）、`wardrobe_mcp.py`（共享工具 / stdio）、`wardrobe/remote.py`（远程 MCP 传输和路径鉴权）、`scripts/make_icons.py`（重绘几何图标）。

## 许可

[MIT](LICENSE)。可以使用、修改、分发和商用，请保留许可证。
