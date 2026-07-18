任务名称：初始化 pmt_analysis 项目骨架与 CLI 入口
## 1. 任务目标
为 pmt_analysis 建立最小可运行的 Python 包结构与命令行入口，并适配真实目录规则：
用户输入单个或多个五位 run_id
程序后续可以根据 run_id 自动查找唯一的 runinfo.json
当前阶段只完成 CLI 和主流程骨架，不实现真实分析逻辑

## 2. 已知数据路径规则
2.1 runinfo 路径规则
每个 run 的 runinfo.json 位于：
/mnt/data/TPC/{runtype}/{run_id}/runinfo.json
其中：
{runtype} 是变化的，例如：
run5_Ar
run6_Xe
run_R8520
{run_id} 是唯一的五位数字
因此，给定 run_id 后，程序应能在：
/mnt/data/TPC/*/{run_id}/runinfo.json
范围内搜索，并找到唯一匹配项。

## 2.2 原始数据路径规则
runinfo.json 中保存了原始数据相关字段，例如：
OUTFILE_PATH = '/mnt/data/TPC/{runtype}/{run_id}/RAW'
OUTFILENAME 中包含：
runtype
采数时间 {年月日-时分秒}
run_id
原始数据位于：
/mnt/data/TPC/{runtype}/{run_id}/RAW/

说明：
当前任务 1 不要求读取原始数据
但项目结构和 CLI 设计必须为后续自动定位数据预留接口

## 3. 本任务完成后应具备的能力
完成后至少应支持：

pip install -e .
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346

运行后命令行应当能：
正确解析子命令 analyze
正确解析一个或多个 run_id
正确解析输出目录
调用统一 pipeline 入口
打印收到的 run_id
明确提示后续将根据 run_id 自动搜索 runinfo.json
当前未实现分析逻辑时，明确提示，而不是静默结束


## 4. CLI 设计要求更新
4.1 保留参数
任务 1 的 CLI 应至少支持：
--run-id：必填，一个或多个五位数字
--output-dir：可选，默认 output
## 4.2 不再作为主要输入的参数
--runinfo-file 不再作为主流程必需参数。
当前阶段建议：
可以完全去掉 --runinfo-file
或者仅保留为 debug/override 参数，但默认不使用
如果保留，必须说明：
这是开发调试用覆盖参数
正常流程应通过 run_id 自动定位 runinfo.json
建议任务 1 中先不暴露 --runinfo-file，保持接口干净。

## 5. 推荐目录结构
```

pmt_analysis/
├── pyproject.toml
├── README.md
├── example_code/
│   ├── pmt_dark_cout_rate_example.ipynb
│   ├── pmt_gain_example.ipynb
│   └── runinfo.json
├── src/
│   └── pmt_analysis/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── pipeline.py
│       ├── io/
│       │   └── __init__.py
│       ├── analysis/
│       │   └── __init__.py
│       ├── plotting/
│       │   └── __init__.py
│       └── db/
│           └── __init__.py
└── tests/

```

## 6. 本任务建议新增文件及职责
6.1 pyproject.toml
职责：
定义项目元信息
使用 src/ 布局
注册 CLI 入口 pmt-analysis
最低要求：
项目名：pmt_analysis
Python：>=3.12
脚本入口：
pmt-analysis = pmt_analysis.cli:main

## 6.2 src/pmt_analysis/__init__.py
职责：
标记包
提供版本号
6.3 src/pmt_analysis/config.py
职责：
存放基础默认配置
建议至少包含：
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_TPC_DATA_ROOT = "/mnt/data/TPC"

说明：
DEFAULT_TPC_DATA_ROOT 后续用于自动搜索：
/mnt/data/TPC/*/{run_id}/runinfo.json

## 6.4 src/pmt_analysis/pipeline.py
职责：
提供统一流程入口
当前阶段只打印基础信息，不做真实搜索和分析
建议函数：
def analyze_runs(run_ids: list[int], output_dir: str) -> int:
    ...

当前功能要求：
接收 run_ids
创建输出目录
打印：
run_ids
output_dir
TPC data root
明确提示：
后续将根据 run_id 自动搜索 runinfo.json
当前版本尚未实现 runinfo 定位与分析模块
返回 0
6.5 src/pmt_analysis/cli.py
职责：
命令行入口
参数解析
调用 pipeline
最低要求：
使用 argparse
提供子命令 analyze
支持：
--run-id，一个或多个整数
--output-dir
建议命令：

pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346

6.6 README.md
职责：
提供安装和最基本用法说明
说明当前通过 run_id 驱动流程
说明 runinfo 将按固定目录规则自动定位

## 7. 推荐接口骨架
src/pmt_analysis/config.py
```
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_TPC_DATA_ROOT = "/mnt/data/TPC"
```
---

src/pmt_analysis/pipeline.py

```
from pathlib import Path
from typing import Sequence

from pmt_analysis.config import DEFAULT_TPC_DATA_ROOT


def analyze_runs(run_ids: Sequence[int], output_dir: str) -> int:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("PMT analysis pipeline started")
    print(f"Run IDs: {list(run_ids)}")
    print(f"Output directory: {output_path.resolve()}")
    print(f"TPC data root: {DEFAULT_TPC_DATA_ROOT}")
    print("Runinfo discovery from run_id is not implemented yet.")
    print("Analysis modules are not implemented yet.")

    return 0
```
---

src/pmt_analysis/cli.py

```
import argparse

from pmt_analysis.config import DEFAULT_OUTPUT_DIR
from pmt_analysis.pipeline import analyze_runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmt-analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze PMT runs")
    analyze_parser.add_argument(
        "--run-id",
        nargs="+",
        type=int,
        required=True,
        help="One or more run IDs to analyze",
    )
    analyze_parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to store outputs",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        raise SystemExit(
            analyze_runs(
                run_ids=args.run_id,
                output_dir=args.output_dir,
            )
        )

    parser.error(f"Unsupported command: {args.command}")
```

## 8. pyproject.toml 推荐骨架
```
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "pmt_analysis"
version = "0.1.0"
description = "PMT test data analysis toolkit"
readme = "README.md"
requires-python = ">=3.9"
authors = [
  { name = "PMT Analysis Team" }
]
dependencies = []

[project.scripts]
pmt-analysis = "pmt_analysis.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

---
## 9. README.md 最低内容骨架
# pmt_analysis

A Python toolkit for PMT test data analysis.

## Current Stage

This repository currently provides:
- package skeleton
- CLI entry point
- basic pipeline placeholder

Not implemented yet:
- automatic runinfo discovery
- raw data reading
- dark count analysis
- SPE gain analysis
- afterpulse analysis
- database writing

## Data Layout

Each run is stored under:

`/mnt/data/TPC/{runtype}/{run_id}/`

Each runinfo file is expected at:

`/mnt/data/TPC/{runtype}/{run_id}/runinfo.json`

The raw data directory is typically:

`/mnt/data/TPC/{runtype}/{run_id}/RAW/`

## Installation

```bash
pip install -e .


Usage
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346 --output-dir output


---

## 10. 代码风格要求

Agent 在任务 1 中应遵守：

1. 使用 ASCII
2. 兼容 Python 3.9+
3. 使用 `argparse`
4. 使用 `pathlib`
5. 函数职责单一
6. 不提前实现 runinfo 搜索逻辑
7. 不读取 notebook
8. 不写数据库
9. 不做无关重构

---

## 11. 本任务不应出现的内容

Agent 不应在任务 1 中做这些事：

1. 解析 `runinfo.json`
2. 搜索 `/mnt/data/TPC/*/{run_id}/runinfo.json`
3. 读取原始数据
4. 实现 dark count
5. 实现 SPE gain
6. 实现 APP
7. 引入数据库逻辑
8. 设计过重抽象

任务 1 的重点仍然只有一个：  
**搭好包结构，跑通 CLI 到 pipeline 的最小链路，并对真实数据路径规则留出明确接口位置。**

---

## 12. 任务 1 完成后的最小验收命令

```bash
pip install -e .
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346 --output-dir output


期望行为：

命令成功执行
输出目录自动创建
打印 run_id 列表
打印 TPC data root
明确提示后续将自动搜索 runinfo.json
明确提示分析模块尚未实现

