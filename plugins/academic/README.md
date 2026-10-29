# 学术研究技能包

本包将 6 个学术技能集中维护，Codex、pi 与 Claude Code 共用包内的 `skills/` 目录，并分别通过各自配置按项目启用。
源文件位于 `~/.agents/plugins/academic/`，不再放入全局自动发现的 `~/.agents/skills/`。
以下依次说明技能范围、启用方式和运行依赖。

## 技能范围

- `wos-paper-search`：检索 WOSCC 论文、元数据、摘要与被引信息
- `query-journal-ranks`：通过 easyScholar 查询期刊分区、影响因子与等级
- `zotero-local-api`：读取本地 Zotero 文献库并导出书目
- `mineru-parse-pdf`：通过 MinerU 将 PDF 解析为 Markdown 交付包
- `gbt-7714-2025-citations`：按 GB/T 7714—2025 审校和转换引用格式
- `academic-writing`：起草和修改理工科中文学术文本，去除大语言模型常见的写作痕迹

每个技能保留自己的触发条件、操作边界、脚本和参考资料。
启用整个包后，代理仍按具体任务选择技能，不会因加载学术包而自动执行检索、读取文献库或上传 PDF。
已有技能中的服务授权条件继续适用。

## Codex 与 pi 按项目启用

Codex 的个人插件目录由 `~/.agents/plugins/marketplace.json` 登记，插件标识为 `academic@personal`。
在 Codex 插件界面安装后，若只希望在学术项目使用，可将下面配置合并进 `~/.codex/config.toml`：

```toml
[plugins."academic@personal"]
enabled = false
```

再将下面配置合并进研究项目的 `.codex/config.toml`，项目须已受信任：

```toml
[plugins."academic@personal"]
enabled = true
```

修改技能源文件后，需更新 Codex 中的本地插件安装副本，并在新对话中使用。
安装与项目开关的行为见 [Codex 插件文档](https://developers.openai.com/plugins/build/plugins)。

pi 在研究项目目录中执行以下命令，将包登记到该项目的 `.pi/settings.json`：

```sh
pi install -l ~/.agents/plugins/academic
```

本地路径直接引用源文件，不复制技能，也不需要发布到包仓库。
在新会话中可通过 `/skill:wos-paper-search` 等命令使用技能。
需要从当前项目移除时，在同一项目目录执行：

```sh
pi remove -l ~/.agents/plugins/academic
```

不要再次把包内技能链接到全局 `~/.agents/skills/`，否则会恢复全局发现。
pi 的项目安装与本地包行为见 [pi 包文档](https://pi.dev/docs/latest/packages)。

## Claude Code 按项目启用

Claude Code 通过 `.claude-plugin/plugin.json` 识别本包。
`~/.claude/skills/academic` 软链接到本目录，Claude Code 将其作为 `academic@skills-dir` 插件加载，直接引用源文件，修改后在新会话中生效。
`~/.claude/settings.json` 中设置了默认禁用：

```json
"enabledPlugins": {
  "academic@skills-dir": false
}
```

在研究项目目录中执行以下命令，在项目的 `.claude/settings.json` 中启用；只在本机启用时将 `-s project` 换为 `-s local`：

```sh
claude plugin enable academic@skills-dir -s project
```

项目级设置覆盖用户级设置，启用后技能名带插件前缀，例如 `academic:wos-paper-search`。

## 运行依赖

Python 环境与依赖使用 `uv` 管理，默认选择 Python 3.13；执行脚本时根据实际加载的 `SKILL.md` 定位路径。
WoS 检索需要具备订阅授权的机构网络、校园网或机构 VPN，并由单文件脚本声明 `requests` 依赖。
Zotero 需要桌面客户端运行并启用 Local API。
MinerU 需要 poppler 提供 PDF 探查工具，并从 `MINERU_API_KEY` 或 `MINERU_TOKEN` 读取凭据。

easyScholar 脚本保留原有个人密钥配置，也支持通过 `EASYSCHOLAR_SECRET_KEY` 或密钥文件覆盖。
因此本包用于个人本地使用，`package.json` 已设置 `private: true`；如需对外分享，应先移除脚本中的个人密钥。
打包本身不会连接上述服务，也不会验证账号授权或消耗解析额度。
