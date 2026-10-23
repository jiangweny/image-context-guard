# Image Context Guard

![Image Context Guard 封面](封面.jpg)

通过隔离子 agent 或独立视觉 API 请求分析图片，让主会话保留可追溯的文字结果。

[English](README.en.md) · [第一次上传 GitHub](docs/FIRST_GITHUB_UPLOAD.md) · [设计与限制](docs/DESIGN.md) · [测试状态](docs/VALIDATION.md)

**状态：v0.1.0 实验版。** 这是社区工具，与 OpenAI 无隶属关系。它不修改 Codex 插件，不提供运行时拦截，不保证解决所有卡顿、断线或压缩失败。61 项离线测试在本地 Linux 环境通过；优化后的原生子 agent 流程完成了一张人工图片的两次实际查看，两次均读出 4827，主会话日志的内嵌图片条目保持 0 → 0。这是同一 worker 的复核，不是独立审阅或性能基准。独立 API 的真实服务端验证仍待完成。详见 [验证记录](docs/VALIDATION.md)。

## 它做什么

~~~text
本地图片 + 一个具体问题
          ↓
隔离的原生子 agent / 独立 Responses API 请求
          ↓
保存文字观察、原图路径、文件哈希和用量
          ↓
主会话只接收文字结果；需要复核时再请求原图
~~~

- 图片保留在磁盘，由原生子 agent 或配置的 API 分析。主会话只收文字与结果路径。
- API 首次观察可复用相同任务缓存；显式二审必须发起新请求，并保存独立证据。
- 提供只读历史检查，以及针对已停止会话的备份、图片块清理和恢复。
- 提供 Codex Skill；可选安装全局规则，帮助 agent 自动选择该流程。

它**不能撤回已经粘贴到主会话中的图片**，也不能通过修改 JSONL 清除运行中的内存上下文。技能选择依赖 agent 遵循指令，不是强制 hook。

## 选择读图方式

| 方式 | 适合的环境 | 执行方式 |
| --- | --- | --- |
| native-agent | 客户端提供获准使用的隔离子 agent，原生读图可用 | Skill 指导 agent 调用客户端工具；不需要 Python 直接连 API |
| api | 独立 API 网络可达，配置了视觉 Responses 模型和 API key | 使用 read_image.py 发起单独请求 |
| auto | 希望依据当前可用能力选择 | 优先允许且可用的隔离子 agent，否则选择支持的 API 路径 |

开源版默认 auto。native-agent 是执行规则，不是本项目附带的子 agent 启动器；命令行 icg.py read 始终是 API 方式。客户端禁止委派、不能隔离历史或无子 agent 工具时，技能不能制造该能力。

原生方式默认一张原图一个任务、最多两个并发。保存首遍和所需复核证据；长时间无可观察进展时先检查，必要时停止旧任务、确认退出后再从断点接替，每张图默认最多接替一次。停止任务不保证释放线程总额，达到硬上限时保存进度并报告。详见 [子 agent 执行规则](skills/image-context-guard/references/native-agents.md)。

本轮或本批次已确认失败的代理/API 路径不会逐图重试；需要配置变化或明确测试才再次探测。该选择是任务级记录，不是永久禁用某个服务商。

## 环境要求

- Python 3.11 或更高版本。
- 独立读图需要 requests，以及支持图片输入的 Responses API 和 API key。
- 使用 Codex 配置顶层的 provider、model、model_reasoning_effort；不继承当前聊天的临时模型覆盖。配置使用 profile 时会拒绝猜测，请提供专用配置目录。
- 历史修改仅面向 Linux/macOS 等支持 POSIX 文件锁的系统。Windows 可运行读图和只读检查；尚未在本地验证 Windows/macOS 行为。
- 历史格式是 Codex 内部实现，版本兼容性有限。未知图片结构拒绝修改，操作前必须停止目标会话。

## API 方式：快速开始

在项目目录打开终端。Linux/macOS：

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
~~~

Windows PowerShell：

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

后续示例中的 python 指安装了依赖的 Python；Windows 可替换为 .venv\Scripts\python.exe。

### 1. 检查配置，不发网络请求

默认读取 CODEX_HOME；未设置时读取用户主目录下的 .codex。不会修改原有配置。

~~~bash
python icg.py read --image examples/demo.png --prompt-file examples/question.txt --out outputs/demo.json --dry-run
~~~

如果没有现成配置，把 examples/config.example.toml 复制到一个本地私有目录，填写自己的模型和 endpoint，再使用 --codex-home 指向该目录。不要把真实配置或密钥提交到仓库。

认证依次使用：provider 的 env_key 指定的环境变量；否则 CODEX_API_KEY / OPENAI_API_KEY；否则所选配置目录 auth.json 中的 OPENAI_API_KEY。不支持浏览器登录 token。该脚本不自动切换供应商、模型或认证方式。

### 2. 发起一次实际读图

下面会向配置的服务商发送人工测试图片，可能产生 API 费用。

~~~bash
python icg.py read --image examples/demo.png --prompt-file examples/question.txt --out outputs/demo.json
~~~

人工图片内容是数字 **4827**。原生子 agent 测试已读出该结果，但上述 API 命令尚无真实服务端成功记录。成功后重跑同一命令应显示 cached: true。完整文字保存在输出 JSON；终端只输出有限长度的摘要，不输出原始图片数据。

常用参数：

| 参数 | 用途 |
| --- | --- |
| --image | 原图路径，可重复，最多三张；通常逐张处理 |
| --prompt / --prompt-file | 一个具体问题或 UTF-8 提示文件 |
| --out | 文字结果和缓存文件，建议放在 outputs/ |
| --codex-home | 指定配置目录，不修改当前 Codex 设置 |
| --effort / --detail | 显式调整推理和图片细节设置，需模型支持 |
| --max-total-mib | 原图总字节预算，默认 8 MiB；这是本地策略 |
| --max-output-tokens / --timeout | 输出预算、整个请求 worker 的总时限（秒） |
| --review-pass review | 重新观察图片，禁止把缓存当二审；建议使用新的 --out |
| --refresh --overwrite | 明确重新请求并替换已有输出 |

配置变化或问题变化时优先选择新的 --out。详细帮助：python icg.py read --help。

--timeout 由父进程监督独立请求 worker，涵盖连接、上传、等待和流式响应；到期停止本次 worker 并回收资源，不保存部分结果。系统调度/进程回收存在开销，不是实时系统保证；停止本地请求也不保证远端服务立即停止计费。

错误输出包含 error_type、phase、http_status、elapsed_seconds、retryable、next_action。区分权限、代理、认证、限流、服务错误、连接失败、总时限等；retryable 只是诊断，不会自动循环重试。响应不完整不会写入成功缓存。

需要二审时，使用新的问题和输出文件：

~~~bash
python icg.py read --image examples/demo.png --prompt-file examples/question.txt --review-pass review --out outputs/demo-review.json
~~~

二审结果记录 review_pass、独立 request_id 和耗时。它证明发起了另一次请求，不证明模型一定正确或审阅质量相互独立。

## 安装到 Codex（两种方式通用）

~~~bash
python install.py --dry-run
python install.py
~~~

安装器默认复制到 CODEX_HOME/skills/image-context-guard；未设 CODEX_HOME 时使用用户主目录的 .codex。不同客户端可用 --skills-dir 指定其技能发现目录，例如 ~/.agents/skills。安装器在目标技能中记录当前 Python 路径，因此请保留对应虚拟环境。

需要同时添加全局读图规则时：

~~~bash
python install.py --with-global-rule --replace --backend auto
~~~

--replace 只用于确认替换已存在的同名技能；替换前会备份。全局规则仅更新带标记的本工具区块，保留其他指令。如果存在 AGENTS.override.md，安装器拒绝自动修改全局规则，请人工核对优先级。安装可能需要当前环境的文件写入授权。

若你的原生子 agent 已可用，而直接 API 请求受代理限制，可选择：

~~~bash
python install.py --with-global-rule --replace --backend native-agent --max-native-agents 2
~~~

--no-progress-seconds 默认 300，仅触发检查，不自动杀死任务。重新安装未指定的偏好会保留原值。native-agent 模式需要客户端自己的登录/网络能力；它并非离线识别。

安装后重启或重载 Codex，并明确调用一次：

~~~text
使用 $image-context-guard 分析 /绝对路径/图片.png，回答……
~~~

新会话可根据技能描述自动匹配；已打开的会话不保证立即重载全局规则。直接给图片路径最适合该流程。脚本失败时，应报告错误，不自动把图片回传主会话。

## 已有会话：检查、清理、恢复

本节是独立恢复功能，不是默认读图流程。**先保存文字交接文件，关闭目标会话，并确认其所属进程已停止写入。** 应从其他会话或终端操作。

~~~bash
python icg.py history audit --session UUID
python icg.py history prune --session UUID --checkpoint /path/to/handoff.md
python icg.py history prune --session UUID --checkpoint /path/to/handoff.md --apply
python icg.py history restore --manifest /path/from/cleanup/manifest.json
python icg.py history restore --manifest /path/from/cleanup/manifest.json --apply
~~~

将 UUID 和文件路径换成实际值。在 agent 中可用 audit --session current；普通终端应提供 UUID 或完整 JSONL 路径。使用自定义配置目录时，将 --codex-home 放在 audit/prune/restore 子命令前。

不加 --apply 仅预览。清理只替换已识别的内嵌图片块，保留其他记录；完整备份保存在所选 Codex home 的 image-context-backups/。拒绝修改当前会话、仍被锁定的记录或未知图片结构。恢复前校验文件未出现新消息。操作结束后重新打开目标会话。

完整历史和备份都可能含隐私数据，不能提交到 GitHub。日志累计大小也不等于实际 API 请求大小。详见 [恢复说明](skills/image-context-guard/references/recovery.md)。

## 项目文件

~~~text
icg.py                          命令行入口
install.py                      可选技能与规则安装器
skills/image-context-guard/      可独立分发的技能和脚本
examples/                       人工测试图片、任务提示、配置示例
tests/                          离线行为测试，不读取真实会话或密钥
tools/                          样例生成与发布目录检查
docs/                           设计、验证记录、首次发布教程
.github/                        自动测试与问题报告模板
~~~

运行离线检查：

~~~bash
python -m unittest discover -s tests -v
python tools/check_release.py
~~~

欢迎提交带版本信息和人工复现数据的 Issue 或 Pull Request，参见 [贡献说明](CONTRIBUTING.md)。发布目录检查是辅助措施，不是完整的密钥检测器。许可证为 [MIT](LICENSE)。
