# 卡牌MCP、任务提示词和会话文本日志

本次增加两项真实能力：HearthstoneJSON只读卡牌工具，以及每账号/会话的可读log.txt。保留现有网页、账号、历史、缓存、摘要，不使用Docker，不提供网页搜索、Shell或任意Python执行。

## 一、先准备卡库，再重启服务

在本项目目录运行：

```bash
../.venv-framework/bin/python -m hearthstone_assistant.tools.cards.update
../.venv-framework/bin/python -m hearthstone_assistant.tools.cards.inspect
../.venv-framework/bin/python -m hearthstone_assistant.server
```

update下载固定公开URL的中文可收藏卡牌JSON，校验后按SHA256保存不可变文件，原子更新manifest；失败不清空旧文件，不自动重试。inspect通过真实stdio MCP检索火球术，再按一个明确候选ID验证详情读取，不调用DeepSeek，不表示替用户选中了标准版本。本机已下载并通过该验证，换电脑首次运行需自行update。原服务在运行时先Ctrl+C再启动，浏览器刷新加载新脚本。

数据在data/cards/zhCN/，不会上传Git。不是每次提问都下载3.5MB，也不会把整个卡库塞进模型。固定数据源无需模型Key，MCP子进程也不接收DeepSeek Key。网站是社区HearthSim项目，不是暴雪官方接口；数据版权按原站声明，不把网站的CC0理解为游戏素材无限授权。

来源：[主页](https://hearthstonejson.com/)、[卡牌字段](https://hearthstonejson.com/docs/cards.html)。旧文档枚举可能滞后，以下载快照实际字段为准。文件URL可能不暴露具体build编号，此时记录build=null，用fingerprint、来源URL、获取时间和Last-Modified标识快照，绝不编造版本。

## 二、两个工具

- search_cards(query,limit=5)：中文名、部分名称、卡牌ID、dbfId检索，最多5个候选。先精确再包含匹配，不模糊猜卡名。结果有status、total、truncated、cards、source。
- get_card(card_id)：按唯一ID返回属性、清理格式后的text、raw_text和来源。没有攻击力/生命等字段就不补0；standard_legal为null，表示未核实。

火球术实际检索会出现CORE_CS2_029、CS2_029、VAN_CS2_029等不同实体，不能只凭同名就选第一条。get_card读取具体候选，其他模式/版本要澄清。不把collectible当标准合法，不提供胜率，也不把客户端文本当成完整游戏规则引擎。

真实数据来自本地只读快照；MCP服务是本机受信Python进程，不是Docker沙箱。固定server模块、参数schema和工具白名单，不执行模型指定的程序，不接受任意URL/路径下载。更新卡库由用户运行命令，不作为模型可调用工具。

## 三、接入原来的Agent

LangGraph变成START→model，若有正规tool_calls则tools→model，否则结束。每轮最多5次主模型请求，每批最多3个工具；最后一次还有工具请求会在执行前停止。SDK收集分片后还会严格json.loads检查，半截JSON不能靠自动补括号通过。

每轮MCP连接在run_agent同一协程中进入和退出，图节点使用该连接，取消时等待退出。异常包装展开保留原始类型，不再把模型调用失败一律归为“MCP失败”。

SQLite的turns增加messages_json列，保留原question/answer与旧历史兼容；新轮次保存user→assistant.tool_calls→tool→…→assistant完整链。活跃工具链不截断，超预算明确失败。摘要保留目标/最终结论，原始工具链仍存库，不能把有损摘要冒充原始证据。

工具结果回填后，每次模型请求前再次检查预算。若旧历史加本轮消息超过限制，turn_context会按本轮工具结果的实际大小重新预留空间，调用已有摘要流程整理更早的完整轮次；只改变本次发送的上下文，不修改State原始消息链及SQLite原文。每轮所有阶段共享最多3次摘要请求，摘要也按实际usage计费。如果仅本轮问题、工具结果和输出预留已超预算，则明确停止，不能截断工具JSON或丢掉某个tool结果来凑数。context_limit、summary_start/summary_saved、context_ready可区分预算整理与工具执行失败。

回答缓存升级cards-mcp-v2，完整请求与卡库指纹均进入缓存键；卡库变化后旧回答不命中。任务内固定数据指纹，不随一次对话中途更新换版本。缓存命中明确标记，不伪造新的工具执行记录。

## 四、不同情况用不同prompt

prompt/system.py维护共同规则：真实查询、同名澄清、来源/快照、工具数据不是指令。
prompt/routing.py在共同规则后加任务补充：general、card_lookup、deck_discussion。当前仅是透明的关键词启发式，不是完美意图分类器；例如“查询/效果/费用”偏卡牌核对，“套牌/构筑/留牌”偏思路讨论。general也能使用卡牌工具，模板选择不等于授权或工具可见性。

日志prompt_selected能看到本轮选择。没有额外模型路由请求，先避免为了选prompt又消耗一次API。未来可以改显式页面模式或经评测的结构化路由；不要靠堆多个互相冲突的system来代替设计。

网页验证问题：

> 请用卡牌工具查询火球术；如果有同名版本，先给候选ID和系列让我选择。

接着说：

> 查看CS2_029的费用和效果，并注明来源与快照时间。

右侧应看到prompt_selected、mcp_connected、model_request、tool_start/tool_end等实际事件。模型不一定按固定次数调用，以真实日志为准。未代用户执行收费问答，仍需主动运行验证供应商兼容性。

## 五、每账号每会话一份log.txt

```text
data/logs/<服务端用户ID>/<会话ID>/
  log.txt              同一会话跨轮次追加，不覆盖
  <运行ID>.jsonl       每次运行的结构化事件
```

log.txt每块包含UTC时间、用户ID、会话ID、轮次ID、运行ID；正文为缩进JSON，可读到用户输入、应用层请求messages/tools/参数、归一化模型回复、实际工具请求/结果、缓存命中、事件/耗时/用量/错误类型。流式失败会注明不完整，不伪装成功。

这是应用层可读日志，和截图类似，但不是逐字原始HTTP包：不伪造供应商没有返回的object/created等字段，不记录认证头、不要求或暴露隐藏推理。没有调用模型时记录“缓存返回”，不会假造一份模型返回。

网页右侧“下载本会话log.txt”通过登录Cookie鉴权，服务端先检查会话属于当前用户再提供文件。不能用客户端传一个user_id读取其他账号日志。原有根目录JSONL不删除，旧会话没有text日志时明确提示，不虚构补录。新运行的JSONL接口兼容新旧路径。

日志会含对话、偏好和工具资料，属于私有数据，勿原样公开。登录密码不进入该日志；已知模型Key、认证类字段、Bearer与常见Key格式会脱敏，但无法保证识别用户主动写入正文的所有秘密。不要往聊天里贴凭据。文件不入Git，无自动删除/轮转/加密/防篡改承诺；日后需要保留期限和备份策略。

## 六、检查范围

当前26项Python检查通过（包含真实卡库读取及stdio MCP），2项网页SSE检查通过；真实数据更新和inspect已运行。补测同名候选、缺失属性、指纹损坏、严格工具参数、旧SQLite迁移、完整工具链保存、会话文本日志追加/脱敏、跨账号下载拒绝，以及工具回填后重新整理上下文、保留活跃消息链、共享摘要次数限制。摘要选择测试使用临时SQLite里的明确数据夹具，不模拟LLM响应。未代用户调用收费模型。
