# easyScholar 期刊等级接口参考

## 接口与响应

- 方法：`GET`
- 地址：`https://www.easyscholar.cc/open/getPublicationRank`
- 参数：`secretKey`、`publicationName`
- 成功外层结构：`{"code": 200, "msg": "SUCCESS", "data": {...}}`
- 失败时 `data` 通常为 `null`，以 `code` 和 `msg` 为准。

`data.officialRank.all` 是该期刊命中的全部官方数据集，`data.officialRank.select` 是用户在 easyScholar 扩展端选中的子集。无结果的字段不会返回，所以解析时必须按可选字段处理。

2026-07-20 的实际探测还确认：

- `rankInfo` 可以存在而 `rank` 为空，这只表示账户配置了自定义数据集，但当前期刊未命中自定义等级。
- `publicationName` 含 `&` 时必须百分号编码；附带脚本使用 `urlencode`。
- 数字型指标在响应中表现为字符串，例如影响因子与 JCI；不得强制转换后丢失原始格式。
- 响应不含榜单年份或版本字段，不得从数值自行推断年份。
- Zotero 7 本地 API 的 `/api/users/0/items/top` 返回对象数组，刊名位于每项的 `data.publicationTitle`。受限沙箱可能无法访问宿主机的 `127.0.0.1:23119`，即使 Zotero 已启用本地通信。

## 自定义等级解码

`customRank.rank` 的每项形如 `uuid&&&n`。按以下顺序解码：

1. 以第一次出现的 `&&&` 分割 UUID 与等级序号。
2. 在 `rankInfo` 中按 UUID 找到数据集，展示其 `abbName`。
3. 将序号 `1` 至 `5` 映射到 `oneRankText`、`twoRankText`、`threeRankText`、`fourRankText`、`fiveRankText`。
4. UUID、序号或等级文字缺失时保留原始编码并发出警告。

## 官方字段

| 字段 | 数据集或指标 |
|---|---|
| `sciif` | SCI 影响因子（JCR） |
| `sciif5` | SCI 五年影响因子（JCR） |
| `sci` | SCI 分区（JCR） |
| `ssci` | SSCI 分区（JCR） |
| `jci` | JCI 指数（JCR） |
| `sciwarn` | 中科院预警 |
| `sciBase` | SCI 基础版分区（中科院） |
| `sciUp` | SCI 升级版分区（中科院） |
| `sciUpSmall` | 中科院升级版小类分区 |
| `sciUpTop` | 中科院升级版 Top 分区 |
| `esi` | ESI 学科分类 |
| `ccf` | 中国计算机学会 |
| `zhongguokejihexin` | 中国科技核心期刊 |
| `fms` | FMS |
| `ajg` | ABS 学术期刊指南 |
| `utd24` | UTD24 |
| `ft50` | FT50 |
| `eii` | EI 检索 |
| `cscd` | 中国科学引文数据库 |
| `pku` | 北大核心 |
| `cssci` | 南大核心 |
| `ahci` | A&HCI |
| `xr` | 新锐学术 |
| `xrWarn` | 新锐学术预警 |
| `xrTop` | 新锐学术 Top 分区 |
| `xrSmall` | 新锐学术小类分区 |
| `swufe` | 西南财经大学 |
| `cufe` | 中央财经大学 |
| `uibe` | 对外经济贸易大学 |
| `sdufe` | 山东财经大学 |
| `xdu` | 西安电子科技大学 |
| `swjtu` | 西南交通大学 |
| `ruc` | 中国人民大学 |
| `xmu` | 厦门大学 |
| `sjtu` | 上海交通大学 |
| `fdu` | 复旦大学 |
| `hhu` | 河海大学 |
| `cqu` | 重庆大学 |
| `nju` | 南京大学 |
| `xju` | 新疆大学 |
| `cug` | 中国地质大学 |
| `cju` | 长江大学（不是计量大学） |
| `zju` | 浙江大学 |
| `scu` | 四川大学 |
| `cpu` | 中国药科大学 |

服务端以后可能增加字段。遇到未知字段时展示字段代码和原始值，不得丢弃。
