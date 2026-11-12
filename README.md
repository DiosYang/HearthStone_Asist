# 炉边 · Hearthside

一个逐步开发的炉石传说学习助手：**网页版客户端 + FastAPI服务端 + LangChain/DeepSeek + LangGraph + SQLite + 只读卡牌MCP**。不使用Docker，不自动操作游戏。

非暴雪官方产品。卡牌来自HearthstoneJSON快照，不是实时游戏/天梯数据。

网页源码独立放在 `web/`。服务端持有模型Key，浏览器只通过同源API交互；不需要Node构建，也不依赖外部CDN。

## 已实现

- 注册、登录、退出；密码加盐哈希、HttpOnly会话Cookie，服务端确认用户身份。
- 每个用户独立会话，新建/选择/搜索会话，重启后恢复完整历史。
- 真实DeepSeek流式回复、停止生成、断线清理与明确的完成状态。
- 用户主动保存/删除的长期偏好；当前任务State与会话缓冲分开。
- 上下文预算与增量摘要，工具回填后超预算会重新整理旧轮次，保留本轮完整工具链；原文保留，摘要请求单独计入用量。
- 15分钟精确回答缓存：用户、会话、模型配置和完整上下文均需匹配。
- 可见运行轨迹、首个可见文本延迟、模型耗时、实际可得token用量。
- 同会话任务串行，用户/全局限并发；请求编号幂等，已完成请求重放而不重新调用模型。
- search_cards/get_card只读工具，真实MCP协议接入；同名卡候选澄清，按唯一ID查效果。
- 固定系统规则+本轮任务prompt，逐轮记录选择；每账号/会话独立可读log.txt，可在网页下载。
- SQLite中完整轮次和任务终态原子提交，重启不自动重做未完成任务。

暂未实现网页检索、套牌码解析、标准合法性、实时胜率或检查点续跑。卡牌回答注明ID及快照来源，不凭快照推断当前热修/模式合法性。

## 快速启动

需要Python3.11或以上。在仓库根目录：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

把 `.env.example` 复制为 `.env`，在本机编辑填入自己的 `DEEPSEEK_API_KEY` 和可用模型名。**不要把真实Key提交Git或填到网页里。**

```bash
python -m hearthstone_assistant doctor
python -m hearthstone_assistant.tools.cards.update
python -m uvicorn hearthstone_assistant.server.app:app --host 127.0.0.1 --port 8000 --workers 1
```

打开 **http://127.0.0.1:8000**，创建自己的助手账号，发送一个小问题开始。账号不是战网/GitHub账号，勿使用重要服务的同一密码。

在原课程环境也可直接从项目目录启动，不必重建环境：

```bash
../.venv-framework/bin/python -m uvicorn hearthstone_assistant.server.app:app --host 127.0.0.1 --port 8000 --workers 1
```

启动后才会使用自己的真实数据库；测试使用独立临时SQLite。真实发送问题/生成摘要会消耗API额度，组件验证不代用户发起付费模型请求。

## 项目结构

```text
web/                          网页客户端（HTML/CSS/JS）
hearthstone_assistant/
  server/app.py               FastAPI接口、认证、SSE、取消与并发
  server/repository.py        按操作创建连接的SQLite访问与账号存储
  server/service.py           上下文→偏好→缓存→图执行→完整提交
  agents/run.py               LangGraph模型/工具循环与工作State
  models/deepseek.py          LangChain异步流式DeepSeek
  prompt/system.py            助手职责、事实和能力边界
  prompt/routing.py           本轮任务提示补充
  tools/cards/                卡库快照、MCP服务/客户端、更新与检查
  memory/context.py           短期上下文选择、增量摘要
  storage/sqlite.py           会话/轮次/摘要/缓存基础存储
  cache/answers.py            精确请求指纹
  log/events.py               允许字段的JSONL事件日志
  log/session.py              每账号/会话可读log.txt及脱敏
  config.py                   服务端配置、模型URL白名单
  __main__.py                 保留的本机doctor/CLI开发入口
tests/                        不调用付费模型的自动检查
docs/网页版-启动与边界.md       当前功能、接口与限制
data/                         私有SQLite/日志，Git忽略
```

tools/现已包含真实卡牌MCP，不使用假的工具结果。网页长期偏好集中为职业、风格、预算和回答方式，由用户明确保存。旧CLI的 `--user` 只是本地开发标识，不等于网页身份；同名注册不会接管旧CLI历史。

## 数据与配置

- SQLite：`data/assistant.sqlite3`；新日志：`data/logs/<用户ID>/<会话ID>/log.txt`及每轮JSONL；旧根目录JSONL仍保留。
- `.env`优先用项目本地文件；原课程环境没有项目.env时可沿用上级.env；终端已有变量优先。
- 不提交.env、DB、日志、登录令牌、缓存或Python虚拟环境。
- 会话摘要有损，不替代原文；估计预算不是精确tokenizer，不承诺绝对不超供应商窗口。
- 相同问题在上下文变化后通常缓存不命中；缓存不是语义问答复用，也不是任务幂等。
- 取消不撤销已完成的数据库提交；看到部分文字不等于已保存，网页会查询终态。
- 删除长期偏好不自动清除旧聊天或日志。

## 验证

```bash
python -m unittest discover -s tests -v
node --test web/sse.test.js
```

Node仅用于网页协议测试，不是运行网页的必要依赖。验证真实临时SQLite/HTTP接口和缓存路径；缓存夹具明确不是模型输出，并禁止意外模型联网。浏览器检查覆盖注册、主页、偏好和桌面/手机断点。

## 安全与部署范围

这是**本机学习版**，默认只绑定127.0.0.1，只接受localhost/127.0.0.1 Host；不要直接用0.0.0.0公开。必须单worker：进程内任务锁/限流尚非分布式实现。

远程部署前需要HTTPS、可信域名/反向代理、账号注册与恢复策略、持久化限流、备份/删除/审计策略等评审。当前不含邮箱验证、忘记密码或公网运维保障。公开代码仓库不是公开运行中的AI服务，GitHub Pages也不能直接运行Python后端。

详细阅读：[网页版启动与边界](docs/网页版-启动与边界.md)、[会话与上下文](docs/会话与上下文.md)。架构与CS原始设计文档保留为演进记录，以本README和网页版说明为当前实现准则。

最新工具与日志说明：[卡牌MCP与会话文本日志](docs/卡牌MCP与会话文本日志.md)。本机已实际下载卡库并完成MCP检查，源码仓库不包含下载的数据；换机器先update。26项Python、2项SSE检查通过；真实DeepSeek工具选择仍由用户主动运行验收。
