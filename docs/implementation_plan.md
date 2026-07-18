- - -

**二、`pmt_analysis` 分阶段实现清单和接口设计**

``` md
# pmt_analysis 分阶段实现清单和接口设计

## 1. 总体实现策略
项目采用“先骨架、后接算法、再接验证、最后接写库”的方式推进。

原则：
1. 先统一输入输出接口
2. 再把 notebook 里的逻辑模块化
3. 每个阶段都必须可运行
4. 每个阶段尽量可测试
5. 写库放在最后接入

---

## 2. 阶段划分

### 阶段 0：需求落盘与材料梳理
目标：
- 固化项目需求
- 整理 `example_code/` 内容
- 明确 notebook 中分别包含哪些逻辑

输入：
- `example_code/pmt_dark_cout_rate_example.ipynb`
- `example_code/pmt_gain_example.ipynb`
- `example_code/runinfo.json`

输出：
- `docs/agent_development_brief.md`
- `docs/implementation_plan.md`

状态：
- 可立即开始

---

### 阶段 1：项目骨架与 CLI
目标：
- 建立 Python 包结构
- 建立命令行入口
- 支持 `run_id` / `run_id list` 输入

建议交付内容：
- `pyproject.toml`
- `src/pmt_analysis/cli.py`
- `src/pmt_analysis/__init__.py`
- `src/pmt_analysis/config.py`
- `src/pmt_analysis/pipeline.py`

CLI 示例：
```bash
pmt-analysis analyze --run-id 12345
pmt-analysis analyze --run-id 12345 12346


验收标准：

包可安装

CLI 可执行

能解析命令参数并进入主流程

阶段 2：runinfo 抽象层
目标：

支持从 runinfo.json 获取 run 信息

统一 run 信息模型

建议交付内容：

src/pmt_analysis/runinfo.py

src/pmt_analysis/models.py

建议核心接口：
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass
class RunInfo:
    run_id: int
    data_type: Optional[str]
    file_path: Optional[str]
    metadata: Dict[str, Any]
    source: str


def load_runinfo_from_json(path: str) -> dict:
    ...

def get_runinfo(run_id: int, runinfo_path: str) -> RunInfo:
    ...



验收标准：

能从 runinfo.json 获取指定 run_id 信息

若缺失 run，给出清晰报错

输出统一 RunInfo 对象

阶段 3：原始数据读取层
目标：

从 notebook 中抽取数据读取方式

封装统一 reader 接口

不把 notebook 代码原样堆进 CLI

建议交付内容：

src/pmt_analysis/io/raw_reader.py

建议接口：

from typing import Any

class RawDataReader:
    def read(self, runinfo: RunInfo) -> Any:
        raise NotImplementedError


class NotebookBasedRawDataReader(RawDataReader):
    def read(self, runinfo: RunInfo) -> Any:
        ...



说明：

这里的 Any 可在读完 notebook 后替换成更明确的数据结构

如果 dark count 和 gain 的输入数据结构不同，可进一步拆分 reader

验收标准：

使用样例 run 能读取数据

能打印基础信息，例如事件数、通道数、波形长度或时间窗口

阶段 4：dark count rate 模块
目标：

抽取 notebook 中 dark count 分析逻辑

封装成可复用函数

输出结构化结果

建议交付内容：

src/pmt_analysis/analysis/dark_count.py

建议接口：

from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class DarkCountResult:
    run_id: int
    pmt_id: str
    total_dark_count: float
    total_daq_time: float
    dark_count_rate: float
    asymmetry_threshold: float
    noise_count: float
    metadata: Dict[str, Any]


def analyze_dark_count(data: Any, runinfo: RunInfo) -> list[DarkCountResult]:
    ...



必须实现：

统计 dark count 总数

获取总 DAQ 时间

计算 dark count rate

使用 asymmetry > 0.7 过滤噪声

打印关键参数

建议验证输出：

asymmetry 分布图

dark pulse count 分布或相关检查图

验收标准：

样例数据结果与 notebook 行为一致

能打印中间统计量

能保存验证图

阶段 5：SPE gain 模块
目标：

抽取 notebook 中 SPE gain 逻辑

封装积分、拟合、结果输出

建议交付内容：

src/pmt_analysis/analysis/spe_gain.py

建议接口：

from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class SpeGainResult:
    run_id: int
    pmt_id: str
    gain: float
    fit_mean: float
    fit_sigma: float
    fit_amplitude: float
    fit_success: bool
    integration_window: tuple[float, float]
    metadata: Dict[str, Any]


def analyze_spe_gain(data: Any, runinfo: RunInfo) -> list[SpeGainResult]:
    ...



必须实现：

使用默认积分窗口

提取用于拟合的数据

单高斯拟合

输出最佳高斯参数

拟合失败时给出清晰标记

建议验证输出：

积分量分布直方图

高斯拟合叠加图

验收标准：

样例数据结果与 notebook 一致或趋势一致

拟合参数可打印

拟合图可保存

阶段 6：统一结果模型与 pipeline
目标：

将 dark count 与 SPE gain 接到统一流程中

为单个 run 输出汇总对象

建议交付内容：

src/pmt_analysis/pipeline.py

src/pmt_analysis/models.py

建议接口：

from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class AnalysisBundle:
    run_id: int
    runinfo: RunInfo
    dark_count_results: list[Any] = field(default_factory=list)
    spe_gain_results: list[Any] = field(default_factory=list)
    afterpulse_results: list[Any] = field(default_factory=list)
    plot_paths: list[str] = field(default_factory=list)
    ready_for_db: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)



def analyze_run(run_id: int, runinfo_path: str, output_dir: str) -> AnalysisBundle:
    ...



def analyze_runs(run_ids: list[int], runinfo_path: str, output_dir: str) -> list[AnalysisBundle]:
    ...



验收标准：

单个 run 能跑完整流程

多个 run 能批量执行

输出结构统一

阶段 7：验证绘图模块
目标：

统一管理验证图保存

保证写库前可人工检查

建议交付内容：

src/pmt_analysis/plotting/validation.py

建议接口：



def plot_dark_count_validation(... ) -> str:
    ...

def plot_spe_gain_validation(... ) -> str:
    ...



def plot_dark_count_validation(... ) -> str:
    ...

def plot_spe_gain_validation(... ) -> str:
    ...



class DatabaseWriter:
    def write_bundle(self, bundle: AnalysisBundle) -> None:
        raise NotImplementedError("Database writer is not implemented yet.")


def confirm_before_db_write(bundle: AnalysisBundle) -> bool:
    ...


当前要求：

CLI 中预留 --write-db 参数位也可以，但默认关闭

未提供写库 example code 前，调用写库必须明确报未实现

验收标准：

不发生真实写入

接口位置清晰可扩展

阶段 9：APP 模块预留
目标：

预留 afterpulse 模块与接口，等待 notebook 补充后实现

建议交付内容：

src/pmt_analysis/analysis/afterpulse.py

建议接口：

def analyze_afterpulse(data: Any, runinfo: RunInfo):
    raise NotImplementedError("Afterpulse analysis is not implemented yet.")


阶段 10：测试与文档
目标：

为关键模块补充基础测试

写清楚安装和使用说明

建议交付内容：

tests/test_runinfo.py

tests/test_pipeline.py

tests/test_dark_count.py

tests/test_spe_gain.py

README.md

验收标准：

至少核心纯逻辑部分有单测

README 能说明如何运行

3. 推荐接口总览
CLI

def main() -> None:
    ...


runinfo

def load_runinfo_from_json(path: str) -> dict:
    ...

def get_runinfo(run_id: int, runinfo_path: str) -> RunInfo:
    ...



raw reader


class RawDataReader:
    def read(self, runinfo: RunInfo):
        ...


dark count

def analyze_dark_count(data, runinfo: RunInfo) -> list[DarkCountResult]:
    ...

spe gain

def analyze_afterpulse(data, runinfo: RunInfo):
    ...


pipeline

def analyze_run(run_id: int, runinfo_path: str, output_dir: str) -> AnalysisBundle:
    ...

def analyze_runs(run_ids: list[int], runinfo_path: str, output_dir: str) -> list[AnalysisBundle]:
    ...


plotting

def plot_dark_count_validation(... ) -> str:
    ...

def plot_spe_gain_validation(... ) -> str:
    ...


db writer

class DatabaseWriter:
    def write_bundle(self, bundle: AnalysisBundle) -> None:
        ...
