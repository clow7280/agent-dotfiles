# MCP 归属清单

本文件手工维护，不参与任何自动同步。
目的是记录每个 MCP server 在三端的配置位置，避免重复添加与版本漂移。

pi 没有原生 MCP 支持，对应机制是 npm extension，通过 `pi install` 安装。

## 归属表

| server          | Claude Code | Codex         | pi   |
|:----------------|:------------|:--------------|:-----|
| chrome-devtools | plugin 提供 | `config.toml` | 无   |
| ask-claude      | 无          | personal 市场 | 扩展 |

## 维护约定

- `chrome-devtools` 在 Claude Code 侧由 `chrome-devtools-mcp` 插件提供，不要再执行 `claude mcp add`
- Codex 侧用 `codex mcp list` 查看当前状态，配置写在 `~/.codex/config.toml`
- pi 侧的扩展列在 `~/.pi/agent/settings.json` 的 `packages` 字段
- 任一端增删 MCP 后回来更新本表
