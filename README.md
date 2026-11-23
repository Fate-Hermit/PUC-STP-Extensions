# PUC 风格斯坦纳树扩展实例生成器（MHC16 / MCC50 / BIP86）

本项目根据 PUC（Pontifícia Universidade Católica do Rio de Janeiro）斯坦纳树基准实例的 **HC、CC、BIP 三类构造规则**，生成可用于 Steiner Tree Problem in Graphs（STP，图上的斯坦纳树问题）实验的扩展实例。输出采用 **SteinLib STP Format Version 1.0**。

> **定位说明**：本项目实现的是 PUC **实例构造规则的独立扩展**，并非原作者的官方生成器，也不能将生成文件视为原始 SteinLib/PUC 实例的逐字节副本。尤其是 CC 终端覆盖码使用独立实现的贪心初始化与禁忌搜索，BIP 使用下述较新的 SCP 源矩阵。

[English documentation](README.en.md)

本仓库代码树发布生成器、配置及来源核验清单，不放置大型 STP 输出或 SCP 矩阵；本次核验所用的 47 个 SCP 输入文件快照通过 GitHub Release 单独提供。

## 1. 数据集概览

| 数据集 | 生成参数/原始输入 | 配置或来源数 | U 型 | P 型 | 有效 STP 文件数 |
|---|---|---:|---:|---:|---:|
| **MHC16** | 超立方体维度 `d = 13, ..., 20` | 8 | 8 | 8 | **16** |
| **MCC50** | 25 组互不重复的 `(n, q)` | 25 | 25 | 25 | **50** |
| **BIP86** | 47 个 SCP 原始矩阵（其中 43 个转换后终端连通） | 43 个有效来源 | 43 | 43 | **86** |
| **合计** | | **76** | **76** | **76** | **152** |

同一配置只生成一对 `u/p` 实例。两者具有**相同的顶点、边和终端集合**，仅边权不同，不另行生成多个随机种子重复样本。

- **U 型**：未扰动边权。HC/BIP 的所有边权为 `1`；CC 的边权为 `1、2、3`。
- **P 型**：按 PUC 对应的边权类别添加整数随机扰动。固定随机种子以便复现。
- **文件名**：`hc13u.stp` / `hc13p.stp`、`cc4-18u.stp` / `cc4-18p.stp`、`bipi1u.stp` / `bipi1p.stp`。

## 2. 运行环境与推荐目录结构

- Python **3.10+**（HC 生成器使用 `int.bit_count()`）；生成代码仅使用 Python 标准库，无需安装第三方 Python 包。
- Linux/WSL、Windows 和 macOS 均可运行核心生成脚本；Windows 可将命令中的 `python3` 换为实际 Python 解释器。
- 三类批量生成默认仅依赖标准库；`MCC50/generate_cc.py` 的可选 `--cover-method exact` 模式另需 NumPy/SciPy，不属于 MCC50 默认配置。
- 大实例生成耗时和磁盘占用较大，建议串行执行并提前预留空间。

仓库保留三类生成器各自的目录。以下命令均从仓库根目录执行：

```text
PUC-STP-Extensions/
├── README.md
├── README.en.md
├── MHC16/
│   └── generate_hc13_20.py
├── MCC50/
│   ├── generate_MCC50_PUC.py
│   ├── generate_cc.py
│   └── MCC50_manifest_template.csv
├── BIP86/
│   ├── convert_puc_bip.py
│   ├── test_converter.py
│   ├── source_connectivity.csv
│   ├── source_files.sha256
│   └── scp/                 # 从 Release 输入快照解压得到，不提交到代码树
│       ├── scpi1.txt
│       ├── scpnrg1.txt
│       └── rail507.txt
├── stp/                     # 运行生成器后建立，未提交
│   ├── MHC16/
│   ├── MCC50/
│   └── BIP86/
└── instance/                # 运行后生成的 JSON 与清单，未提交
    ├── MHC16/
    ├── MCC50/
    └── BIP86/
```


## 3. MHC16：超立方体实例

### 3.1 生成标准

采用 `d` 维二进制超立方体。顶点为所有 `d` 位二进制向量；仅当两个顶点的二进制表示恰好相差一位时连边。以二进制中 `1` 的个数为**偶数**的顶点作为终端。

\[
|V|=2^d,\qquad |E|=d\,2^{d-1},\qquad |T|=2^{d-1}.
\]

- **U 型**：每条边权重均为 `1`。
- **P 型**：每条边独立伪随机取 `[100,110]` 范围内的整数（含两端）。
- **维度**：`13,14,15,16,17,18,19,20`，共 8 组。
- **种子**：`BASE_SEED = 20261010`；P 型按 `20261010 + 1000*d` 生成。U 型不需要随机种子。

| 参数 | 最小值（HC13） | 最大值（HC20） |
|---|---:|---:|
| 顶点数 | 8,192 | 1,048,576 |
| 边数 | 53,248 | 10,485,760 |
| 终端数 | 4,096 | 524,288 |

### 3.2 使用方式

```bash
# 查看 HC13—HC20 的计划规模，不生成文件
python3 MHC16/generate_hc13_20.py plan

# 先测试一个维度，生成 hc13u.stp 和 hc13p.stp
python3 MHC16/generate_hc13_20.py generate --dimension 13 \
  --outdir ./stp/MHC16 --meta-dir ./instance/MHC16

# 生成全部 16 个文件
python3 -u MHC16/generate_hc13_20.py generate --all \
  --outdir ./stp/MHC16 --meta-dir ./instance/MHC16

# 校验单个已生成实例
python3 MHC16/generate_hc13_20.py verify ./stp/MHC16/hc13u.stp --dimension 13
```

关键参数：`--dimension`（指定维度）、`--all`（生成全部维度）、`--variant u|p|both`（默认 `both`）、`--outdir`、`--meta-dir`、`--overwrite`、`--skip-existing`。如果存在旧文件，生成器默认拒绝覆盖；`--skip-existing` 是跳过已存在文件，不等同于重新验证其完整性。

## 4. MCC50：覆盖码 / Hamming 图实例

### 4.1 生成标准

使用 `q` 元 `n` 维 Hamming 图 `H(n,q)`：顶点是全部 `n` 维 `q` 元向量，Hamming 距离恰好为 `1` 的顶点之间连边。

\[
|V|=q^n,\qquad |E|=\frac{n(q-1)q^n}{2},\qquad \deg(v)=n(q-1).
\]

终端集合是**覆盖半径为 1 的覆盖码**（等价于图上的支配集）：每个顶点自身是终端，或至少与一个终端相邻。使用固定种子的**贪心初始化 + 禁忌交换搜索**选择终端；会验证覆盖条件，但**不保证终端数达到理论最小值**。同一 `(n,q)` 的 U/P 共用该终端集合。

设一条边的两个端点中有 `t∈{0,1,2}` 个终端：

- **U 型边权**：`1+t`，故分别为 `1、2、3`。
- **P 型边权**：`100(1+t)+ξ`，其中 `ξ` 为独立伪随机整数，均匀取自 `{0,...,10}`；对应区间为 `[100,110]`、`[200,210]`、`[300,310]`。

**25 组定稿参数：**

| `n` | `q` 的取值 | 组数 |
|---:|---|---:|
| 4 | 11、12、13、14、15、16、17、18 | 8 |
| 5 | 7、8、9、10、11 | 5 |
| 6 | 6、7 | 2 |
| 7 | 5 | 1 |
| 8 | 4 | 1 |
| 9 | 4 | 1 |
| 10 | 3 | 1 |
| 11 | 3 | 1 |
| 13—17 | 2（每个 `n` 一组） | 5 |
| **合计** | | **25** |

对应 **50 个 U/P 文件**。本组的最大顶点数为 **262,144**（`cc9-4`），最大边数为 **4,026,275**（`cc5-11`）；边数和顶点数的最大值不一定来自同一配置。

**定稿默认参数**：`--tabu-steps 120`、`--tabu-levels 4`、`--tabu-restarts 2`；覆盖半径 `r=1`；边权扰动模式为 `prng`。每组种子由版本标识 `MCC50-PUC-CC-v2` 与 `(n,q)` 组合后，通过 SHA256 确定性导出。修改版本标识、参数或算法实现可能改变终端和边权。

> 该禁忌搜索是**独立实现**，不是 PUC 参考文献所使用的原始覆盖码禁忌搜索程序；因此只保证符合 Hamming 图、覆盖半径、边权类别等构造规则，不宣称复制原始 PUC 的终端集合。

### 4.2 使用方式

```bash
# 预览 25 组配置、图规模；默认仅预览，不写入 STP
python3 MCC50/generate_MCC50_PUC.py

# 只测试一组（cc13-2u/p）
python3 MCC50/generate_MCC50_PUC.py --run --only cc13-2 \
  --stp-dir ./stp/MCC50 --meta-dir ./instance/MCC50

# 生成完整 MCC50
python3 -u MCC50/generate_MCC50_PUC.py --run \
  --stp-dir ./stp/MCC50 --meta-dir ./instance/MCC50 \
  > ./mcc50_generation.log 2>&1
```

关键参数：`--run`（真正开始生成）、`--only ccN-Q`（指定一组，可重复使用）、`--stp-dir`、`--meta-dir`、`--tabu-steps`、`--tabu-levels`、`--tabu-restarts`、`--overwrite`、`--max-nodes`、`--max-edges`、`--generator`。默认启用生成后校验；不推荐使用 `--no-verify`。批量驱动输出 `MCC50_manifest.csv` 规划表；每个 STP 对应的 JSON 记录终端数、覆盖校验结果、参数及 SHA256。

`MCC50_manifest.csv` 是完整 25 组配置的规划清单，包含待测内存状态；即使用 `--only`，也不能将该文件当作已生成文件列表。修改 tabu 参数后须使用新输出目录或加 `--overwrite`；已有匹配文件会按配置与 SHA256 跳过，不会自动因 tabu 参数变化而重建。

默认规模限制为 `--max-nodes 262144`、`--max-edges 4100000`，这是候选实例的**结构筛选线**，不是对求解器内存的保证。

## 5. BIP86：由集合覆盖问题（SCP）转换的二部图

### 5.1 生成标准

输入是一个 `m×n` 的二值 SCP 关联矩阵 `A`。构造无向二部图：

1. 每个 **SCP 行**转为一个**终端**，编号 `1,...,m`。
2. 每个 **SCP 列**转为一个**非终端**，编号 `m+1,...,m+n`。
3. **当且仅当** `A[i,j]=1`，增加一条边 `(i,m+j)`；不增加行—行或列—列的边。
4. **忽略 SCP 文件原有的列成本**，只保留其 0/1 关联结构。
5. U 型边权全部为 `1`；P 型每条边伪随机取整数 `[100,110]`（含两端）。

因此：

\[
|V|=m+n,\qquad |E|=\#\{(i,j):A[i,j]=1\},\qquad |T|=m.
\]

BIP 使用 `RANDOM_MASTER_SEED = 20261023`。每个 SCP 来源标识与主种子通过 SHA256 导出独立的确定性子种子。**不会重采样、更改、删减 SCP 的矩阵结构，也不会为了使图连通而人工加边。**

### 5.2 SCP 数据来源与数量

| 原始 SCP 系列 | SCP 文件数 | 有效 BIP（U/P）数 | 转换说明 |
|---|---:|---:|---|
| I、J、K、L、M、N | 30 | 60 | Umetani 发布的六个大规模 SCP 系列，每系列 5 份 |
| NRG、NRH | 10 | 20 | OR-Library，各系列 5 份 |
| RAIL507、RAIL582、RAIL2536 | 3 | 6 | OR-Library，转换后终端连通 |
| RAIL516、RAIL2586、RAIL4284、RAIL4872 | 4 | **0** | 转换后终端不连通，默认隔离 U/P 共 8 个文件 |
| **合计** | **47** | **86** | **43 个有效 SCP 来源，每个来源生成一对 U/P** |

原始矩阵的提供方与论文见第 8 节：I—N 系列（30 个）来自 Umetani，NRG/NRH 与 RAIL（17 个）来自 OR-Library。为保留本次使用的输入版本，Release `scp-inputs-v1` 提供 [47 个 SCP 输入文件快照（scp-inputs-v1.zip）](https://github.com/Fate-Hermit/PUC-STP-Extensions/releases/download/scp-inputs-v1/scp-inputs-v1.zip)。压缩包包含 `scp/` 下的 47 个文件、`SHA256SUMS` 和说明来源及格式的 `SNAPSHOT.md`；它们不放入 Git 代码树。

从仓库根目录下载并解压到 `BIP86/`，即可直接使用第 5.4 节的 `--scp-dir ./BIP86/scp` 命令：

```bash
curl -fL https://github.com/Fate-Hermit/PUC-STP-Extensions/releases/download/scp-inputs-v1/scp-inputs-v1.zip -o scp-inputs-v1.zip
python3 -m zipfile -e scp-inputs-v1.zip BIP86

# Linux/WSL：核对压缩包内每个输入文件的 SHA256
(cd BIP86 && sha256sum -c SHA256SUMS)
```

Windows PowerShell 可将 `curl` 换为 `curl.exe`、`python3` 换为实际 Python 解释器。也可通过上述链接手动下载，将压缩包内容解压到 `BIP86/`，得到 `BIP86/scp/`。代码树中的 [`source_files.sha256`](BIP86/source_files.sha256) 也记录这 47 个输入的哈希。

本转换器读取按行稀疏格式：先写 `m n`、再写 `n` 个列成本，随后逐行写关联列数与 1 起始列号。快照中的 47 个文件均为本次核验所用的本地行式输入，**其中 RAIL 是本地行式副本；OR-Library 官网的 RAIL 原始下载采用按列格式，不能原样输入本转换器。**本文档的 43/47 可行数量与 RAIL 分量数结论针对快照及哈希清单所列文件；本仓库不包含 RAIL 从官网列式原件转为行式输入的预处理步骤，未独立核验两者的逐项矩阵等价性。如从原提供方重新获取文件，须准备相同的行式输入并核对哈希；Umetani 页面提供的 [SCP 数据包入口](https://drive.google.com/file/d/17im3dxfYdiGO2bUtJxX08kuyimIdsJ7d/view)见原作者数据页面。

47 个 SCP 输入来自上述原始数据提供方，**不属于本项目原创数据**。Release 快照保留这些来源说明，不为源矩阵另行授予新许可证；使用和再分发须遵守原始数据提供方的条件。

### 5.3 BIP 特别注意事项：不连通的 RAIL 源实例

以下四个原始矩阵按 PUC-BIP 规则转换后，终端分属不同连通分量，因此无法形成连接所有终端的斯坦纳树：

| SCP 来源 | 含终端的连通分量数 | 对应隔离文件 |
|---|---:|---|
| `rail516` | 14 | `biprail516u.stp`、`biprail516p.stp` |
| `rail2586` | 8 | `biprail2586u.stp`、`biprail2586p.stp` |
| `rail4284` | 5 | `biprail4284u.stp`、`biprail4284p.stp` |
| `rail4872` | 8 | `biprail4872u.stp`、`biprail4872p.stp` |

转换器默认使用 `--invalid-policy quarantine`，将上述文件放到 `stp/BIP86/infeasible/`，保留其原始拓扑记录。**不要将这 8 个文件混入 BIP86 正式求解集**；其求解失败意味着数据不存在可行斯坦纳树，不应计作求解器的算法性能失败。

**数量口径**：`47` 个 SCP 输入 × `2` 个边权版本 = `94` 个转换输出；其中 `8` 个被隔离，**可用 BIP86 = 86 个**。如使用其他 SCP 数据，实际可行数量应以连通性检查为准。默认隔离策略还会隔离全图不连通但终端仍连通的来源（例如存在孤立非终端列）；此次 47 个来源没有这种额外情形。

### 5.4 使用方式（推荐直接读取 `BIP86/scp/` 文件夹）

```bash
# 直接从 BIP86/scp/ 读取；不需要重新压缩 ZIP
# 先检查识别到多少个 SCP 文件（完整原数据应为 47 个）
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp --list

# 可选：预扫描矩阵及终端连通性，不写入 STP
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp \
  --meta-dir ./instance/BIP86 --scan-only

# 先测试一个小来源：BIP86/scp/scpi1.txt -> bipi1u/p.stp
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp --only i1 \
  --outdir ./stp/BIP86 --meta-dir ./instance/BIP86 \
  --verify-after-write

# 转换完整 SCP 数据集：94 个输出，其中 8 个默认隔离
python3 -u BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp \
  --outdir ./stp/BIP86 --meta-dir ./instance/BIP86 \
  --verify-after-write > ./bip86_conversion.log 2>&1

# 查看进度
tail -f ./bip86_conversion.log

# 校验一个已生成的 STP 文件
python3 BIP86/convert_puc_bip.py --verify ./stp/BIP86/bipi1u.stp
```

如果原始数据只有 `scp.zip`，也可以将 `--scp-dir ./BIP86/scp` 换成 `--zip ./scp.zip`，**不必先解压**。文件夹和 ZIP 均必须包含相同的原始 SCP 矩阵内容，才能得到对应的一致拓扑及边权。

关键参数：`--scp-dir`（直接读目录）、`--zip`（读压缩包）、`--only i1 rail507`（只转指定 SCP 来源）、`--outdir`、`--meta-dir`、`--seed`、`--list`、`--scan-only`、`--verify-after-write`、`--verify`、`--overwrite`、`--invalid-policy quarantine|keep`。其中 `--invalid-policy keep` 会把不可行图放在普通输出目录，**不建议用于正式实验集**。

已对本次 47 个来源完成逐项解析与连通性检查：43 个可行、4 个终端不连通。结果见 [`BIP86/source_connectivity.csv`](BIP86/source_connectivity.csv)；原始输入的 SHA256 见 [`BIP86/source_files.sha256`](BIP86/source_files.sha256)。这些来源都可以被解析和转换；被排除的原因是转换图不存在可行 STP 解，而非文件格式不支持。

元数据目录包含 `conversion_summary.csv`、`conversion_summary.json` 以及每个实例的 `.json` 文件，记录源矩阵、图规模、终端连通性、随机种子及 STP SHA256。

## 6. 可复现性、正确性与内存约束

### 6.1 如何复现同一批文件

- 保留**相同版本**的生成脚本，特别是 `generate_MCC50_PUC.py` 必须与其配套 `generate_cc.py` 一起使用。
- 保留相同配置、随机种子、SCP 源文件和生成顺序；不要修改排序、随机流或文件头格式。
- 每组参数只生成一对 U/P，不增加随机重复版本。
- 生成后对照 `.json` 中的 `sha256` 检验 `.stp`；若要与过去已发布数据逐字节对比，请先保存旧文件的 `sha256sum` 清单。
- HC、CC、BIP 的 STP 可重复生成；但 JSON 中的生成耗时、绝对路径等字段不保证逐字节相同。


### 6.2 结构校验不等于内存验证

本项目原始实验对 TJ 求解器设置了**单实例峰值 RSS 小于 4 GiB**的约束，并建议用 **3.2 GiB** 作为安全预检线。应注意：

1. 生成器对顶点数、边数或磁盘文件大小的检查，**不能证明** TJ 的峰值内存满足限制。
2. 每个实际用于比较的 STP 实例应使用**目标机器上的最终求解器可执行文件**单独测量峰值 RSS。
3. 不应将“内存超限/被系统杀死”和“算法未找到可行解”混为一谈。
4. BIP 中的 `infeasible/` 是**终端不连通**造成的数学不可行，与内存限额无关。

## 7. 修改参数以进一步扩展

上述固定参数对应**固定版 152 个有效实例**。若要发布更多不同规模的实例，应新建版本并保存独立清单，避免覆盖原始结果。

- **HC**：在 `generate_hc13_20.py` 中调整 `MIN_DIM/MAX_DIM`，并保证维度、种子和输出命名不冲突；更高维度可能产生极大的边数。
- **CC**：修改 `generate_MCC50_PUC.py` 中的 `PROFILES`。当前批量驱动对 **恰好 25 个互不重复配置**有显式检查；若要新增而不是替换配置，必须同步修改该检查、输出总数及内存限制。更改 tabu 参数会改变终端集合。
- **BIP**：向 `BIP86/scp/` 添加合规 SCP 关联矩阵即可扩展来源，但文件名映射后的来源 ID 应唯一。须重新执行 `--scan-only`，排除终端不连通的图；不能人为补边后仍称为同一原始 SCP 转换实例。

扩展后的实例需要重新记录参数、数量、终端集合、SHA256 和实际求解器 RSS；不得直接把新数据称为本 README 的 MHC16/MCC50/BIP86。

## 8. 原始规则与 SCP 数据来源（引用建议）

**PUC 的 HC / CC / BIP 构造规则：**

1. I. Rosseti, M. Poggi de Aragão, C. C. Ribeiro, E. Uchoa, and R. F. Werneck, *New Benchmark Instances for the Steiner Problem in Graphs*, Research Report, Department of Computer Science, Catholic University of Rio de Janeiro, 2001. https://optimization-online.org/2001/09/374/

**SCP 数据来源：**

2. S. Umetani, *Exploiting variable associations to configure efficient local search algorithms in large-scale binary integer programs*, *European Journal of Operational Research*, vol. 263, no. 1, pp. 72–81, 2017. https://doi.org/10.1016/j.ejor.2017.05.025 （其 Table 1 使用 I—N 与 RAIL 系列 SCP 实例）
3. S. Umetani, *Set Covering Problem Benchmark Instances*, 作者公开数据页面（I—N 系列，每系列 5 份）：https://sites.google.com/view/umepon/benchmark
4. J. E. Beasley, *OR-Library: Distributing test problems by electronic mail*, *Journal of the Operational Research Society*, vol. 41, no. 11, pp. 1069–1072, 1990. OR-Library：https://people.brunel.ac.uk/~mastjjb/jeb/orlib/scpinfo.html （NRG、NRH、RAIL 系列）

引用实例集时建议同时引用 **[1]（PUC 构造规则）**与 **[2]—[4]（SCP 实例及来源）**。本项目未证明扩展实例与原始 PUC 基准具有相同的最优值或相同的算法难度。

---

**版本提示**：本 README 描述的是 **HC13—HC20 / MCC50-PUC-CC-v2 / BIP86 文件夹输入版**。若代码或来源数据发生变化，请同时更新版本说明和哈希清单。


## 9. 发布核验

本次发布修正了目录示例、MCC/BIP 默认输出路径与 Windows 下的 UTF-8 JSON 读取；图构造规则、默认种子、参数配置和权重生成逻辑不变。

- MHC13 的 U/P 生成与独立校验通过，文件 SHA256 与原有参考元数据一致。
- MCC `cc13-2` 按默认参数生成、完整校验及两次独立生成一致性检查通过。
- BIP 的 47 个源矩阵已全部扫描；4 个不连通 RAIL 来源见第 5.3 节。
- BIP 自带的人工矩阵测试可用 `python3 BIP86/test_converter.py` 执行。

这些核验不表示本次已重新生成所有 152 个大型实例，也不表示已经完成求解器内存测量。
