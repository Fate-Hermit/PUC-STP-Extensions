# BIP86: SCP 关联矩阵到 STP 二部图

完整说明及命令见[仓库主 README](../README.md)和[英文说明](../README.en.md#bip86-bipartite-graphs-converted-from-scp)。

47 个输入包括 Umetani 的 I—N 系列 30 个、OR-Library 的 NRG/NRH 系列 10 个以及 RAIL 系列 7 个。原始矩阵未随仓库发布，请从主 README 中的来源下载并放入本目录的 `scp/`。

输入必须是按行稀疏 SCP 格式：`m n`、`n` 个列成本、逐行的关联列数及 1 起始列号。本次 47 个已核验文件均为此格式。OR-Library 官网的 RAIL 原始下载采用按列格式，需要先转成按行格式，不能直接交给本解析器。请核对来源 SHA256。

本文档的数量与连通性结论针对该哈希清单中的本地行式输入。仓库未包含从官网 RAIL 列式原件生成这些输入的预处理步骤，也未独立验证预处理前后矩阵逐项一致。

按矩阵逐一映射：行是终端，列是非终端，每个非零元素是一条边，忽略原 SCP 列成本，不人为增加连接边。每个来源生成一对 U/P。

`rail516`、`rail2586`、`rail4284`、`rail4872` 转换后分别有 14、8、5、8 个含终端的连通分量，没有连接全部终端的可行斯坦纳树。它们并非格式不支持，转换器仍可输出相应文件，但默认将 8 个输出隔离到 `infeasible/`。正式 BIP86 只包含其余 43 个来源的 86 个输出。

从仓库根目录运行：

```bash
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp --list
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp \
  --outdir ./stp/BIP86 --meta-dir ./instance/BIP86 --verify-after-write
python3 BIP86/test_converter.py
```

默认输出路径为 `stp/BIP86` 和 `instance/BIP86`，相对于当前工作目录。

- `source_connectivity.csv`：此次全部 47 个输入的实际扫描结果。
- `source_files.sha256`：原始输入 SHA256，可用于核对下载内容。
- `scp_archive_inventory.csv`：原有来源规模清单，不能代替连通性扫描结果。
