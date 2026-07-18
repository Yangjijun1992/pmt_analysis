任务名称：实现基于 run_id 的 runinfo 自动发现与解析层

## 1. 任务目标
在现有项目骨架基础上，实现：
根据输入的五位 run_id
在 /mnt/data/TPC/*/{run_id}/runinfo.json 范围内自动搜索 runinfo.json
确保搜索结果唯一
解析 runinfo.json
将结果转换为统一的 RunInfo 数据对象
在 CLI / pipeline 中接入该能力
本任务重点是 runinfo 发现与解析，不实现原始数据读取和分析逻辑。

## 2. 已知路径规则
2.1 runinfo.json 的真实位置
每个 run 的 runinfo.json 位于：
/mnt/data/TPC/{runtype}/{run_id}/runinfo.json

其中：
{runtype} 可变，例如：
run5_Ar
run6_Xe
run_R8520
{run_id} 是唯一五位数字
因此，给定 run_id 后，程序应搜索：
/mnt/data/TPC/*/{run_id}/runinfo.json

## 2.2 原始数据路径线索
runinfo.json 中包含类似字段：
OUTFILE_PATH = '/mnt/data/TPC/{runtype}/{run_id}/RAW'
OUTFILENAME 中包含：
runtype
采数时间
run_id
本任务只需要把这些字段解析并保留到统一对象里，不要求现在读取原始数据。

## 3. 本任务完成后应具备的能力
完成后，以下命令应能工作：
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346

程序行为要求：
对每个 run_id 自动搜索 runinfo.json
若找到唯一匹配：
解析 runinfo
构造成统一 RunInfo
在终端打印关键摘要

若未找到匹配：
给出清晰错误
若找到多个匹配：
给出清晰错误并列出路径
当前阶段仍不执行原始数据读取和分析，只做到 runinfo 层

## 4. 本任务建议新增/修改的文件
必须新增
src/pmt_analysis/models.py
src/pmt_analysis/runinfo.py

需要修改
src/pmt_analysis/pipeline.py
src/pmt_analysis/cli.py（如有必要，通常只需少量调整）

## 5. 数据模型设计要求
5.1 RunInfo 必须存在
建议使用 dataclass 定义统一对象。
建议字段如下：

```
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class RunInfo:
    run_id: int
    runtype: Optional[str]
    run_dir: Path
    runinfo_path: Path
    raw_dir: Optional[Path]
    outfile_name: Optional[str]
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
```
字段含义说明
run_id
当前 run 的五位数字 ID
runtype
从目录结构 /mnt/data/TPC/{runtype}/{run_id}/runinfo.json 推断得到
run_dir
即 /mnt/data/TPC/{runtype}/{run_id}
runinfo_path
runinfo.json 的完整路径
raw_dir
优先从 OUTFILE_PATH 解析；若缺失，也可根据 run_dir / "RAW" 推断，但要注明推断来源

outfile_name
来自 OUTFILENAME

source
固定标记，例如：
"filesystem:auto_discovery"

metadata
保留原始 JSON 中所有未标准化字段，避免信息丢失

## 6. runinfo 搜索与解析的职责划分
建议将逻辑拆分为以下几个函数：

### 6.1 搜索单个 run 的 runinfo
```
def discover_runinfo_path(run_id: int, data_root: str = "/mnt/data/TPC") -> Path:
    ...

```
职责：
在 data_root/*/{run_id}/runinfo.json 搜索
若找到 0 个，抛出清晰异常
若找到 >1 个，抛出清晰异常并包含候选路径
若找到 1 个，返回该路径

### 6.2 加载 JSON
```
def load_runinfo_json(path: Path) -> dict:
    ...
```

职责：
安全读取 runinfo.json
返回原始字典
对 JSON 格式错误给出清晰异常

### 6.3 从 JSON + 路径构建统一对象
```
def build_runinfo(run_id: int, runinfo_path: Path, payload: dict) -> RunInfo:
    ...
```
职责：
根据路径推断 runtype 和 run_dir
从 JSON 中提取：
OUTFILE_PATH
OUTFILENAME
构造统一 RunInfo
未标准化字段全部保留到 metadata

### 6.4 外部统一调用接口
```
def get_runinfo(run_id: int, data_root: str = "/mnt/data/TPC") -> RunInfo:
    ...
```
职责：
对单个 run_id 完成“发现 + 读取 + 构建对象”

### 6.5 批量接口（可选，但推荐）
```
def get_runinfos(run_ids: list[int], data_root: str = "/mnt/data/TPC") -> list[RunInfo]:
    ...
```
职责：
批量处理多个 run_id

## 7. 异常设计要求
建议显式定义异常，而不是只抛普通 ValueError。
推荐放在 runinfo.py 中。

建议异常类型
```
class RunInfoError(Exception):
    pass


class RunInfoNotFoundError(RunInfoError):
    pass


class RunInfoNotUniqueError(RunInfoError):
    pass


class RunInfoParseError(RunInfoError):
    pass
```

行为要求
未找到
给出类似错误信息：
```
No runinfo.json found for run_id=12345 under /mnt/data/TPC
```
找到多个
给出类似错误信息：

```
Multiple runinfo.json files found for run_id=12345:
- /mnt/data/TPC/run5_Ar/12345/runinfo.json
- /mnt/data/TPC/run6_Xe/12345/runinfo.json
```

JSON 格式错误
给出类似错误信息：
```
Failed to parse runinfo JSON: /mnt/data/TPC/run5_Ar/12345/runinfo.json
```

## 8. 推荐实现细节
### 8.1 使用 pathlib.Path
优先使用：
Python 3.12

搜索方式建议：
Python
如需更严格，也可以先将 run_id 转为字符串。

### 8.2 run_id 合法性检查
建议增加辅助函数：
Python
要求：
接受 int 或数字字符串
校验其是否为五位数字
不合法时报错
允许：
12345
不允许：
1234
123456
abcde
说明：
如果你不想在本任务里加得太重，也可先只校验“正整数 + 五位长度”

### 8.3 从路径推断 runtype 和 run_dir
给定路径：
```
/mnt/data/TPC/run5_Ar/12345/runinfo.json
```
则应推断：
runtype = "run5_Ar"
run_dir = "/mnt/data/TPC/run5_Ar/12345"

实现时可用：
runinfo_path.parent 得到 run_dir
runinfo_path.parent.parent.name 得到 runtype

### 8.4 raw_dir 处理规则
建议优先级：
若 JSON 中有 OUTFILE_PATH 且非空：
使用它作为 raw_dir
否则：
使用 run_dir / "RAW" 作为推断值
若使用推断值，建议在 metadata 中注明，例如：
"raw_dir_inferred": True

### 8.5 metadata 保留要求
不要只抽几个字段后把原 JSON 丢掉。
必须保留原始字段，例如：
Python
然后标准字段照常单独放到 RunInfo 中。

## 9. pipeline 接入要求
当前阶段 pipeline.py 应从“只打印 run_id”升级为：
对每个 run_id：
自动发现 runinfo.json
解析为 RunInfo

打印摘要信息，例如：
run_id
runtype
runinfo_path
raw_dir
outfile_name
建议主流程接口仍保持简单，例如：
Python
```
def analyze_runs(run_ids: Sequence[int], output_dir: str) -> int:
    ...
```
建议打印格式
类似：
```
PMT analysis pipeline started
Run IDs: [12345, 12346]
Output directory: /path/to/output
TPC data root: /mnt/data/TPC

Discovered runinfo for run_id=12345
  runtype: run5_Ar
  runinfo_path: /mnt/data/TPC/run5_Ar/12345/runinfo.json
  raw_dir: /mnt/data/TPC/run5_Ar/12345/RAW
  outfile_name: xxx

Discovered runinfo for run_id=12346
  ...
  
Raw data reading is not implemented yet.
Analysis modules are not implemented yet.
```
## 10. CLI 要求
本任务中 CLI 应保持尽量简单
继续支持：
```
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346
```

可选增强
如果 Agent 愿意，可以增加一个 debug 参数：
--data-root

默认值为：
这样更方便后续测试和本地开发。
如果加入，建议：
在 config.py 中增加：

Python
DEFAULT_TPC_DATA_ROOT = "/mnt/data/TPC"

cli.py 增加：

--data-root

pipeline.py / runinfo.py 接收该参数

建议：本任务中允许加入 --data-root，而且这其实更实用。

## 11. 推荐接口骨架
11.1 src/pmt_analysis/models.py
```
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class RunInfo:
    run_id: int
    runtype: Optional[str]
    run_dir: Path
    runinfo_path: Path
    raw_dir: Optional[Path]
    outfile_name: Optional[str]
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 11.2 src/pmt_analysis/runinfo.py
```
from __future__ import annotations

import json
from pathlib import Path

from pmt_analysis.models import RunInfo


class RunInfoError(Exception):
    pass


class RunInfoNotFoundError(RunInfoError):
    pass


class RunInfoNotUniqueError(RunInfoError):
    pass


class RunInfoParseError(RunInfoError):
    pass


def normalize_run_id(run_id: int | str) -> int:
    ...


def discover_runinfo_path(run_id: int, data_root: str = "/mnt/data/TPC") -> Path:
    ...


def load_runinfo_json(path: Path) -> dict:
    ...


def build_runinfo(run_id: int, runinfo_path: Path, payload: dict) -> RunInfo:
    ...


def get_runinfo(run_id: int, data_root: str = "/mnt/data/TPC") -> RunInfo:
    ...
```
## 11.3 src/pmt_analysis/pipeline.py
建议更新为
```
from pathlib import Path
from typing import Sequence

from pmt_analysis.config import DEFAULT_TPC_DATA_ROOT
from pmt_analysis.runinfo import get_runinfo, RunInfoError


def analyze_runs(run_ids: Sequence[int], output_dir: str, data_root: str = DEFAULT_TPC_DATA_ROOT) -> int:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("PMT analysis pipeline started")
    print(f"Run IDs: {list(run_ids)}")
    print(f"Output directory: {output_path.resolve()}")
    print(f"TPC data root: {data_root}")
    print()

    for run_id in run_ids:
        try:
            runinfo = get_runinfo(run_id=run_id, data_root=data_root)
        except RunInfoError as exc:
            print(f"Failed to resolve run_id={run_id}: {exc}")
            return 1

        print(f"Discovered runinfo for run_id={runinfo.run_id}")
        print(f"  runtype: {runinfo.runtype}")
        print(f"  runinfo_path: {runinfo.runinfo_path}")
        print(f"  raw_dir: {runinfo.raw_dir}")
        print(f"  outfile_name: {runinfo.outfile_name}")
        print()

    print("Raw data reading is not implemented yet.")
    print("Analysis modules are not implemented yet.")
    return 0
```
### 11.4 src/pmt_analysis/cli.py
如果加入 --data-root，建议类似:
```
import argparse

from pmt_analysis.config import DEFAULT_OUTPUT_DIR, DEFAULT_TPC_DATA_ROOT
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
    analyze_parser.add_argument(
        "--data-root",
        default=DEFAULT_TPC_DATA_ROOT,
        help="TPC data root directory",
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
                data_root=args.data_root,
            )
        )

    parser.error(f"Unsupported command: {args.command}")
```
### 12. config.py 推荐更新
```
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_TPC_DATA_ROOT = "/mnt/data/TPC"
```
## 13. README 应补充的内容
Agent 应更新 README，至少说明：
当前程序通过 run_id 自动发现 runinfo.json
默认搜索根目录是：
/mnt/data/TPC
支持用 --data-root 覆盖，方便测试
当前阶段已实现：
包骨架
CLI
runinfo 自动发现与解析
当前阶段未实现：
原始数据读取
dark count
gain
APP
DB 写入
## 14. 本任务不应做的事情
Agent 不应在任务 2 中做这些事：
读取 RAW 原始数据
解析 notebook
实现 dark count
实现 SPE gain
实现 APP
实现数据库写入
设计复杂 ORM 或数据库模型
过度扩展 CLI

## 15. 最小验收标准
情况 A：成功
如果目录中存在：
则执行：
```
pmt-analysis analyze --run-id 12345
```
应能：
自动发现该文件
正确解析并打印摘要
返回成功状态码 0

## 16. 建议 Agent 输出格式
请 Agent 在完成任务时按以下格式回复：

1. 修改文件列表
列出新增和修改的文件
2. 设计说明
说明：
RunInfo 为什么这样设计
runinfo 搜索逻辑如何实现
异常如何处理
pipeline 如何接入
3. 完整代码
给出关键文件完整代码
4. 运行方式
给出典型命令
5. 当前未实现内容
明确后续接入点
6. 风险与假设
例如：
假设 run_id 在整个 /mnt/data/TPC 下唯一
假设 runinfo 文件名固定为 runinfo.json



