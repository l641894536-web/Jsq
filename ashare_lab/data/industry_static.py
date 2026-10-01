"""个股 → 申万一级行业 的静态映射（在拿不到申万官方分类接口时的替代方案）。

来源（均为 PyPI 上公开发布的包内数据文件，运行时从 PyPI 下载，不随本仓库分发）：
1. hikyuu 包 `config/block/hybk.ini`：东方财富 86 个行业板块成分（2024-05 快照，约 5400 只）；
2. abupy 包 `RomDataBu/stock_code_CN.csv`：申万(2014版)一级行业（2017 年快照，约 2900 只，含之后退市的股票）。
优先用 1，1 里没有的（主要是 2017~2024 年间退市的股票）用 2 补。两者都没有的股票（主要是
2024-05 以后上市的新股）不参与行业计算，但仍计入全市场成交额分母。

局限（报告中会注明）：
- 这是“当前/某一时点”的分类，不是点对点历史分类：公司跨行业转型会被按最新归属回溯；
- 东方财富行业→申万一级 的对应是人工对照，个别行业（如“互联网服务”“采掘行业”）存在口径差异。
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

# 东方财富行业板块 → 申万2021一级行业指数代码
EM_TO_SW1 = {
    "光学光电子": "801080", "消费电子": "801080", "电子元件": "801080", "半导体": "801080", "电子化学品": "801080",
    "游戏": "801760", "文化传媒": "801760",
    "计算机设备": "801750", "软件开发": "801750", "互联网服务": "801750",
    "通信设备": "801770", "通信服务": "801770",
    "船舶制造": "801740", "航天航空": "801740",
    "仪器仪表": "801890", "通用设备": "801890", "交运设备": "801890", "专用设备": "801890", "工程机械": "801890",
    "教育": "801210", "旅游酒店": "801210", "专业服务": "801210",
    "装修装饰": "801720", "工程咨询服务": "801720", "工程建设": "801720",
    "生物制品": "801150", "医疗器械": "801150", "化学制药": "801150", "医药商业": "801150", "中药": "801150", "医疗服务": "801150",
    "电网设备": "801730", "电机": "801730", "电源设备": "801730", "风电设备": "801730", "电池": "801730", "光伏设备": "801730",
    "塑料制品": "801030", "非金属材料": "801030", "橡胶制品": "801030", "化学制品": "801030", "化肥行业": "801030",
    "农药兽药": "801030", "化纤行业": "801030", "化学原料": "801030",
    "家用轻工": "801140", "造纸印刷": "801140", "包装材料": "801140",
    "有色金属": "801050", "小金属": "801050", "能源金属": "801050", "贵金属": "801050",
    "汽车零部件": "801880", "汽车服务": "801880", "汽车整车": "801880",
    "家电行业": "801110",
    "纺织服装": "801130", "珠宝首饰": "801130",
    "贸易行业": "801200", "商业百货": "801200",
    "石油行业": "801960", "采掘行业": "801960",
    "美容护理": "801980",
    "装修建材": "801710", "玻璃玻纤": "801710", "水泥建材": "801710",
    "综合行业": "801230",
    "环保行业": "801970",
    "公用事业": "801160", "电力行业": "801160", "燃气": "801160",
    "物流行业": "801170", "铁路公路": "801170", "航运港口": "801170", "航空机场": "801170",
    "食品饮料": "801120", "酿酒行业": "801120",
    "多元金融": "801790", "证券": "801790", "保险": "801790",
    "农牧饲渔": "801010",
    "煤炭行业": "801950",
    "钢铁行业": "801040",
    "银行": "801780",
    "房地产服务": "801180", "房地产开发": "801180",
}

# 申万2014一级（及少量旧名）→ 申万2021一级指数代码
SW2014_TO_SW1 = {
    "机械设备": "801890", "化工": "801030", "医药生物": "801150", "电子": "801080", "电气设备": "801730",
    "计算机": "801750", "公用事业": "801160", "汽车": "801880", "房地产": "801180", "交通运输": "801170",
    "轻工制造": "801140", "建筑装饰": "801720", "商业贸易": "801200", "有色金属": "801050", "纺织服装": "801130",
    "传媒": "801760", "食品饮料": "801120", "通信": "801770", "农林牧渔": "801010", "建筑材料": "801710",
    "家用电器": "801110", "采掘": "801950", "非银金融": "801790", "综合": "801230", "国防军工": "801740",
    "休闲服务": "801210", "钢铁": "801040", "银行": "801780", "交运设备": "801890", "餐饮旅游": "801210",
    "建筑建材": "801710", "黑色金属": "801040", "信息设备": "801750",
}


# 个别权重股的东财归类与申万明显不同，按申万2021口径修正（只收录确定的）
OVERRIDES = {
    "300059": "801790",  # 东方财富：东财归“互联网服务”，申万为 非银金融-证券
}


def parse_hybk(path: Path) -> pd.DataFrame:
    rows, cur = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        m = re.match(r"^\[(.*)\]$", line)
        if m:
            cur = m.group(1)
            continue
        if line and cur:
            code = line.split(",")[-1].strip()
            rows.append({"code": code.zfill(6), "em_industry": cur})
    return pd.DataFrame(rows)


def parse_abupy(path: Path) -> pd.DataFrame:
    a = pd.read_csv(path, dtype={"symbol": str})
    a = a[a["industry"].isin(SW2014_TO_SW1)]
    return pd.DataFrame({"code": a["symbol"].str.zfill(6), "sw2014": a["industry"]})


def download_sources(work_dir: Path, log=print) -> tuple[Path, Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for pkg, member in (("hikyuu", "hikyuu/config/block/hybk.ini"), ("abupy", "abupy/RomDataBu/stock_code_CN.csv")):
        target = work_dir / Path(member).name
        if not target.exists():
            wheels = list(work_dir.glob(f"{pkg}-*.whl"))
            if not wheels:
                log(f"从 PyPI 下载 {pkg}（只取其中的数据文件）")
                subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "-q", pkg, "-d", str(work_dir)], check=True)
                wheels = list(work_dir.glob(f"{pkg}-*.whl"))
            with zipfile.ZipFile(wheels[0]) as z:
                target.write_bytes(z.read(member))
        out[pkg] = target
    return out["hikyuu"], out["abupy"]


def build_static_industry(out_csv: str | Path, work_dir: str | Path, log=print) -> pd.DataFrame:
    hy_path, ab_path = download_sources(Path(work_dir), log)
    em = parse_hybk(hy_path)
    em["sector"] = em["em_industry"].map(EM_TO_SW1)
    unknown = sorted(set(em.loc[em["sector"].isna(), "em_industry"]))
    if unknown:
        log(f"  !! 未映射的东方财富行业：{unknown}")
    em = em.dropna(subset=["sector"]).drop_duplicates("code")
    em["sector"] = em["code"].map(OVERRIDES).fillna(em["sector"])
    ab = parse_abupy(ab_path)
    ab["sector"] = ab["sw2014"].map(SW2014_TO_SW1)
    ab = ab[~ab["code"].isin(em["code"])].drop_duplicates("code")
    both = pd.concat([
        em.assign(source="hikyuu_em_2024")[["code", "sector", "source", "em_industry"]],
        ab.assign(source="abupy_sw2014_2017", em_industry=None)[["code", "sector", "source", "em_industry"]],
    ], ignore_index=True)
    both["start_date"] = "2000-01-01"
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    both.to_csv(out_csv, index=False)
    log(f"写入 {out_csv}：{len(both)} 只（东财2024 {len(em)} 只 + 申万2014补充 {len(ab)} 只）")
    # 交叉校验：两个来源都有的股票，映射到同一申万一级的比例
    ab_all = parse_abupy(ab_path)
    ab_all["sector_ab"] = ab_all["sw2014"].map(SW2014_TO_SW1)
    chk = em.merge(ab_all, on="code")
    if len(chk):
        agree = (chk["sector"] == chk["sector_ab"]).mean()
        log(f"  两个来源重叠 {len(chk)} 只，行业一致率 {agree:.0%}（不一致主要来自2014→2021分类调整与公司转型）")
    return both
