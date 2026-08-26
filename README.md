<h1 align="center">
  <img src="./public/favicon.ico" alt="Data Formulator icon" width="28">&nbsp;
  Data Formulator 中文定制版
</h1>

<p align="center">
  🪄 用 AI Agent 驱动可视化探索数据 —— 中文界面 · 桌面版 · 支持国产大模型
</p>

基于 [microsoft/data-formulator](https://github.com/microsoft/data-formulator)（MIT 许可）的个人定制版本。上传数据或连接数据库后，用自然语言对话即可完成数据加载、转换、可视化和报告生成。

## 本定制版的改动

相对上游版本：

- **界面完全中文化**：默认且仅启用中文（`AVAILABLE_LANGUAGES=zh`），隐藏语言切换按钮
- **移除微软品牌与演示内容**：顶栏"微软研究院"标识、About 页面、页脚微软链接、首页示例板块、内置 Example Datasets 数据源及全部演示资源均已删除，只保留实际可用的功能
- **新增 Windows 桌面版**：PyInstaller + WebView2 打包，双击即用，无需打开浏览器
- **修复**：聊天消息的 Markdown 表格渲染（remark-gfm）、中文 Windows 下的测试编码问题、若干界面细节

保留的核心功能：文件上传（CSV/Excel/JSON/图片/文本）、本地文件夹、数据库连接器（MySQL、PostgreSQL、SQL Server、MongoDB、BigQuery、S3 等）、AI 数据加载助手、Data Thread 探索、30+ 图表类型、报告生成、会话持久化。

## 快速开始

### 方式一：桌面版（推荐日常使用）

双击桌面的 **Data Formulator** 快捷方式，或直接运行：

```
dist\Data Formulator\Data Formulator.exe
```

- 原生窗口，无需浏览器；重复打开会唤起已有窗口而不是新开实例
- 整个 `dist\Data Formulator\` 文件夹是一个整体，移动时需整体移动并重建快捷方式

修改代码后重新打包桌面版：

```bash
yarn build && uv run pyinstaller packaging/data_formulator_desktop.spec --noconfirm
```

> 重新打包前请先关闭正在运行的桌面版，否则 exe 被占用会导致打包失败。

### 方式二：网页版（开发调试用）

需要 Python ≥ 3.11、Node.js、yarn、[uv](https://docs.astral.sh/uv/)。

```bash
# 首次安装依赖
uv sync
yarn install

# 终端 1：启动后端（Flask，端口 5567，代码热重载）
uv run data_formulator --dev

# 终端 2：启动前端（Vite，端口 5173，改代码即时生效）
yarn start
```

打开 http://localhost:5173 （5173 被占用时 Vite 会自动换端口，以终端输出为准）。

不做开发、只想跑起来用：`uv run data_formulator`，会自动打开 http://localhost:5567 。

## 配置大模型（DeepSeek / Qwen 等）

首次使用需配置模型。推荐编程和工具调用能力强的模型（如 `deepseek-v4-pro`、`qwen3-max` 等，以服务商控制台的最新模型 ID 为准）。

**方式一：界面配置（即配即用）**

点击右上角"选择模型" → 添加模型：

| 字段 | DeepSeek | Qwen（阿里云百炼/DashScope） |
|------|----------|------------------------------|
| 提供商 | `openai` | `openai` |
| 模型 | 如 `deepseek-v4-pro` | 如 `qwen3-max` |
| API Key | 你的 DeepSeek Key | 你的 DashScope Key |
| API Base | `https://api.deepseek.com/v1` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

国产模型走 OpenAI 兼容协议，因此提供商选 `openai` 并填写对应的 API Base 即可。OpenAI、Azure、Anthropic、Gemini、Ollama 本地模型同样支持。

**方式二：`.env` 文件（服务端全局配置，需重启后端）**

```env
DEEPSEEK_ENABLED=true
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODELS=deepseek/deepseek-v4-pro
```

更多可配置项见 [.env.template](.env.template)。

**注意**：纯文本模型下"聊天传图"和"AI 看图检查图表"两个功能会静默降级（不报错但无效果），需要视觉能力请选用对应的多模态版本（如 Qwen-VL 系列）。

## 数据存放位置

网页版与桌面版**共用**数据目录 `C:\Users\<用户名>\.data_formulator\`（会话、上传的数据表、凭据保险库）。两边配置的模型和创建的会话互通；迁移或备份时带走该目录及 `.env` 即可。

## 常用命令

```bash
uv run pytest              # 后端测试
yarn test                  # 前端测试
npx tsc --noEmit           # TypeScript 类型检查
yarn build                 # 构建生产版前端（输出到 py-src/data_formulator/dist）
```

更多开发细节（沙箱、部署配置、认证等）见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 许可与致谢

本项目基于 MIT 许可，源自微软研究院的 [Data Formulator](https://github.com/microsoft/data-formulator) 项目，原始版权声明见 [LICENSE](LICENSE)。图表渲染基于开源可视化语言 [Flint](https://microsoft.github.io/flint-chart/)。本定制版仅供个人学习与使用。
