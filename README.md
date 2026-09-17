# Yiyawei（咿呀喂）

把中文口语、重复表达、改口内容，整理成适合粘贴到 ChatGPT、Claude、Gemini、Cursor、VS Code、终端等输入框的专业文本。

这是一个**本地优先的 Windows 语音识别与提示词整理工具**：帮助不熟悉提示词的小白，把自然口述整理成更适合 AI Agent 执行的任务文本。

当前正式支持 Windows 10/11。macOS 尚未适配；欢迎社区基于平台适配层贡献 macOS 实现。

**不是**普通语音转文字，**不是**聊天机器人，**不是**代码生成器。

## 核心原则

不要让 ASR 决定最终表达质量。ASR 只负责把语音转成可用原材料，真正的 Typeless 感来自 LLM 审计层。

当前 ASR 主链路固定为 FunASR Paraformer。后续优化不靠多套 ASR 和词典补丁堆叠，而是让 LLM harness 根据上下文做语义审计。产品质量看 `final_text`，不是看 `raw_asr_text`。

## 核心流程

```
按住快捷键 → 说话 → 松开
    → 本地 ASR
    → 本地 LLM 口语审计
    → final_text
    → 剪贴板 + Ctrl+V 粘贴到当前输入框
```

## 隐私原则

- 全部本地运行
- 不上传语音
- 不上传文本
- 不依赖 OpenAI / Claude / Gemini 等云端 API
- 用户自行配置 Ollama、LM Studio 或 OpenAI-compatible 本地服务

## 环境要求

- Windows 10/11（当前支持平台）
- Python 3.10+
- 可选：NVIDIA GPU（ASR 加速）
- 本地 LLM：Ollama 或 LM Studio

## 快速开始

### 1. 安装依赖

```powershell
# Run these commands from the cloned VoicePromptCompiler directory.
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 启动本地模型（Ollama 示例）

```powershell
ollama serve
```

模型需要由用户单独取得，例如在确认条款后执行 `ollama pull qwen3.5:9b`；极速配置的 `gemma4:e4b` 也需要单独取得。两个值都只是配置示例标签，不是不可变模型 provenance。使用前请确认实际模型 ID、revision/manifest 和模型发布者条款；模型权重不随本仓库分发。

### 3. 修改配置

编辑 `config.yaml`，设置 `llm.model`、`llm.base_url`、快捷键和麦克风设备。ASR 默认使用 FunASR Paraformer。

### 4. 运行

先跑 preflight：

```powershell
python scripts/preflight.py
python scripts/preflight.py --record-test 2
```

如果麦克风默认设备不对，在 `config.yaml` 里把 `recorder.device` 改成 preflight 列出的输入设备 index。

无麦克风时先测 LLM 链路：

```powershell
python app.py --text "帮我看一下登录页，不对不是登录页，是注册页"
```

完整热键链路：

```powershell
python app.py
```

**以管理员身份运行**可提高全局快捷键捕获成功率（`keyboard` 库在 Windows 上的限制）。

### 5. 快捷键（默认）

| 快捷键 | 模式 |
|--------|------|
| `Alt + Space` | 专业整理（默认 LLM） |
| `Alt + Shift + Space` | 极速整理（fast_llm） |
| `Alt + C` | AI 任务需求 |
| `Alt + T` | 终端命令（高风险需确认） |

按住开始录音，松开结束并处理。

实际使用顺序：

1. 先把光标点到 Cursor 聊天框、终端或其他目标输入框。
2. 按住热键说话。
3. 松开热键，等待 ASR 和 LLM 处理完成。
4. 程序通过剪贴板和 `Ctrl+V` 把 `final_text` 粘贴回当前焦点输入框。

如果 `Alt + Space` 与系统窗口菜单或输入法冲突，可先把 `config.yaml` 中 `hotkeys.professional` 改成例如 `ctrl+shift+space`。

## 文本模式测试（无麦克风）

```powershell
python app.py --text "帮我看一下登录页，不对不是登录页，是注册页"
python app.py --text "..." --mode cursor_prompt
```

## 项目结构

```
VoicePromptCompiler/  # physical workspace name is unchanged
├── app.py                 # 主入口
├── config.yaml            # 用户配置
├── src/
│   ├── hotkey/            # 快捷键
│   ├── recorder/          # 录音
│   ├── asr/               # FunASR Paraformer 语音识别
│   ├── llm/               # 本地大模型适配器
│   ├── auditor/           # 口语审计器（核心）
│   ├── glossary/          # 术语表
│   ├── injector/          # 剪贴板与粘贴
│   ├── safety/            # 风险检测
│   ├── storage/           # SQLite 历史
│   ├── plugin_bridge/     # 后续插件预留
│   └── utils/
├── data/
├── tests/
└── docs/
```

## 配置 LLM

### Ollama（默认）

```yaml
llm:
  provider: ollama
  base_url: http://localhost:11434
  model: qwen3.5:9b
```

### LM Studio

```yaml
llm:
  provider: lmstudio
  base_url: http://localhost:1234/v1
  model: your-model-name
```

## 验收清单（MVP）

代码已具备：

- [x] 快捷键按住/松开录音
- [x] 本地 ASR
- [x] 本地 LLM 整理
- [x] 剪贴板 + Ctrl+V
- [x] 风险确认（控制台 y/n）
- [x] SQLite 历史
- [x] config.yaml 可切换模型
- [x] preflight 检测依赖、麦克风、Ollama、CUDA

仍需真机实测：

- [ ] `python scripts/preflight.py --record-test 2` 有清晰麦克风电平
- [ ] Ollama 已启动且 `config.yaml` 中模型存在
- [ ] `python app.py --text "..."` 能完成 LLM 审计
- [ ] Cursor/终端输入框内按住热键说话，松开后能粘贴回当前框

## GUI 优先级

托盘 GUI 建议排在 **P1 高优先级**，紧跟 P0 真机跑通之后做。它能解决“点一下开始/结束说话”和状态反馈，但不替代当前 P0 必须先验证的麦克风、ASR、LLM、粘贴链路。最小版本应是托盘菜单：开始/停止、模式选择、退出；底层复用现有 `run_pipeline` / `process_audio`，避免产生两套语音处理逻辑。

## 后续路线

产品范围见 `docs/product.md`，发布边界见 `docs/OPEN_SOURCE_RELEASE.md`。

## 许可证

本项目代码使用 [Apache License 2.0](LICENSE) 发布。

本项目不会将 Ollama、LM Studio、FunASR、ModelScope、PyTorch 或任何模型权重重新授权为本项目许可证。它们仍受各自项目和模型的许可证约束；使用者需要自行安装并确认对应许可证。

项目当前只承诺 Windows 支持。macOS、Linux 或其他平台的适配可以作为社区贡献，但在对应平台完成构建、权限和端到端验证前，不视为官方支持。

## 开源发布边界

公开仓库只应包含源码、测试、必要的示例配置和文档。不要提交以下内容：

- 个人路径、桌面快捷方式、机器名或本机环境变量
- API key、token、密码、凭据文件或私有配置
- 录音、SQLite 数据库、运行日志和浏览器配置
- ASR/LLM 模型缓存、模型权重和构建产物
- 内部治理收据、交接材料、临时输出和本地评测报告

发布前请检查 `git diff`、`git ls-files` 和仓库历史，确认没有把本机数据误带入公开仓库。公开快照的发布边界见 `docs/OPEN_SOURCE_RELEASE.md`；本文件不包含开发工作树的治理收据或内部交接材料。

## Engineering Gates

The local architecture gates and Windows manual smoke checklist are documented
in [Architecture Stability](docs/architecture_stability.md). Run the core local
checks before handoff:

```powershell
python -X utf8 -m pytest -q
python -X utf8 -m pytest -c pytest.e2e.ini e2e -q
python -X utf8 -m compileall app.py src tests scripts e2e
python scripts/package_preflight.py --out "$env:TEMP/package_preflight.json" --fail-on-error
git diff --check
```

The repository does not claim that hosted CI is configured or online.

## Experimental Local Plugin Bridge

The desktop hotkey path still uses clipboard + `Ctrl+V`. The experimental
plugin bridge is different: it returns JSON to a local caller and never pastes
by itself.

Start the local daemon:

```powershell
python app.py --daemon
```

Optional local token:

```powershell
python app.py --daemon --daemon-token "local-secret"
```

Package/readiness evidence for plugin and packaging work:

```powershell
python scripts/package_preflight.py --out output/package_preflight.json
python scripts/run_governance_gate.py --release --require-package-preflight
```

Deterministic bridge smoke evidence:

```powershell
python scripts/bridge_smoke_evidence.py --out output/bridge_smoke_evidence.json
python scripts/run_governance_gate.py --release --require-bridge-smoke-evidence
```

Optional real LLM benchmark:

```powershell
python scripts/benchmark_processor_real_llm.py --out output/processor_real_llm_benchmark.json
python scripts/run_governance_gate.py --release --require-real-llm-benchmark
```

The real LLM benchmark is explicit live evidence only. The default release gate
does not call the configured model, and the runtime hotkey/plugin paths do not
read this artifact.

Optional offline receipts for the next delivery tracks:

```powershell
python scripts/asr_manual_evidence.py --config config.no_paste.yaml --cases data/asr_manual_evidence_cases.json --out output/asr_manual_evidence.json
python scripts/plugin_poc_preflight.py --plugin-root integrations/vscode-cursor --out output/plugin_poc_preflight.json
python scripts/scan_project_terms.py --terms data/project_terms.json --out output/project_terms_scan.json
python scripts/pyinstaller_readiness.py --spec packaging/VoicePromptCompiler.spec --out output/pyinstaller_readiness.json
```

These are governance receipts. They are not read by the voice compilation hot
path and do not make normal output slower.

For a clean public checkout, generate a source-only governance manifest:

```powershell
python scripts/build_governance_manifest.py --public-snapshot --fail-on-invalid
```

The default manifest mode remains an internal release check and intentionally
requires generated `output/` evidence that is excluded from this public
snapshot.
