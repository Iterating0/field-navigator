"""A small, deliberately bounded teaching map, NOT a generated scientific taxonomy.

Bibliography: Crossref metadata + arXiv 2404.04536; see SOURCES.md.
Relations/confidences/reading priorities are illustrative editorial annotations.
"""
import json
from pathlib import Path
from app.models.schemas import Paper, normalize_field

PAPERS = [Paper.model_validate(p) for p in json.loads(
    Path(__file__).with_name('demo_papers.json').read_text(encoding='utf-8'))]

# name: (summary, prerequisites, subfields, relevant bibliography indexes)
MAP = {
    'Non-Hermitian Skin Effect': (
        '非厄米趋肤效应（NHSE）描述大量本征态向开放系统边界聚集的现象。它揭示了边界条件对能谱与态分布的强烈影响，也是理解非布洛赫能带与非厄米拓扑的重要入口。可以从能带基础出发，再沿理论推广、非相干动力学与实验平台继续探索。',
        ['Non-Hermitian band theory', 'Bloch theory'],
        ['Non-Bloch band theory', 'Higher-dimensional NHSE', 'Incoherent NHSE', 'Experimental realizations'],
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
    'Non-Hermitian band theory': (
        '通过复能谱、左右本征态和点隙等概念研究非厄米周期系统，为区分边界局域化与拓扑边界态提供基础语言。',
        ['Bloch theory'], ['Point-gap topology', 'Non-Bloch band theory'], [0, 1, 2, 3, 4, 8]),
    'Bloch theory': (
        '周期势中的平移对称性允许用准动量组织本征态。理解布里渊区与能带，是比较周期边界和开放边界问题的起点。此演示节点附上连接到非厄米问题的参考材料，而非完整的布洛赫理论教材清单。',
        [], ['Non-Hermitian band theory'], [8, 0, 2]),
    'Non-Bloch band theory': (
        '当常规布洛赫波不能描述开放边界下的体态时，可通过广义布里渊区和复波矢建立能带描述，重审体边对应。',
        ['Bloch theory', 'Non-Hermitian band theory'], ['Generalized Brillouin zone', 'Point-gap topology'], [2, 0, 1, 4, 3]),
    'Higher-dimensional NHSE': (
        '将趋肤效应从一维链拓展到二维及更高维，研究几何形状、边界方向和复能谱如何共同决定局域化。',
        ['Non-Bloch band theory'], ['Geometry-dependent skin effect'], [7, 4, 3, 2, 0]),
    'Incoherent NHSE': (
        '探索失去相位相干之后，非互易输运是否仍能产生边界聚集。可从光子量子行走中的非相干趋肤效应入手，比较波的干涉与概率分布动力学。',
        ['Non-Hermitian band theory', 'Non-Hermitian Skin Effect'], ['Photonic quantum walks'], [9, 6, 8, 3, 0]),
    'Experimental realizations': (
        '通过电路、光学等可控平台观测边界聚集和异常体边对应。阅读时注意实验实际测量的量与理论本征态之间的联系。',
        ['Non-Hermitian Skin Effect'], ['Topolectrical circuits', 'Photonic quantum walks'], [5, 6, 9, 0, 1]),
    'Point-gap topology': (
        '围绕复能量参考点定义谱绕数，为理解部分非厄米趋肤现象提供拓扑视角。具体结论依赖维数、对称性与边界条件。',
        ['Non-Hermitian band theory'], [], [3, 4, 0]),
    'Generalized Brillouin zone': (
        '使用复数形式的传播因子刻画开放边界体态，是一维非布洛赫能带方法中的核心对象。',
        ['Non-Bloch band theory'], [], [2, 0, 4]),
    'Geometry-dependent skin effect': (
        '研究系统边界几何改变时，趋肤模式及能谱如何变化。此演示以高维趋肤效应论文为主要阅读入口。',
        ['Higher-dimensional NHSE'], [], [7, 2, 3]),
    'Photonic quantum walks': (
        '以离散演化步骤模拟输运，可引入非互易性和退相干，比较相干与非相干边界聚集。这里仅展示与 NHSE 相关的阅读入口。',
        ['Non-Hermitian Skin Effect'], [], [9, 6, 0]),
    'Topolectrical circuits': (
        '电路网络可用来实现非厄米耦合并探测响应，为研究广义体边对应提供实验平台。',
        ['Non-Hermitian band theory'], [], [5, 1, 0]),
}

REASONS = [
    '以非厄米拓扑模型讨论边界态与拓扑不变量，是学习非布洛赫描述的重要起点。',
    '从双正交框架讨论体边对应，可与非布洛赫方法对照阅读。',
    '系统发展非厄米系统的非布洛赫能带理论，适合建立计算框架。',
    '讨论趋肤效应的拓扑起源，将边界聚集与复能谱拓扑联系起来。',
    '研究谱绕数与趋肤模式的对应关系，连接拓扑判据与边界现象。',
    '通过非厄米电路平台研究广义体边对应，是理论与实验的连接点。',
    '利用光学平台展示拓扑漏斗效应，可作为观察趋肤输运的实验入口。',
    '研究二维及更高维趋肤效应，帮助理解几何相关现象。',
    '非厄米局域化问题的早期工作，可用于理解非互易模型的历史背景。',
    '直接研究光子量子行走中的非相干趋肤效应，是该分支的针对性入口。',
]


def lookup(query: str):
    return next(((name, entry) for name, entry in MAP.items()
                 if normalize_field(name) == normalize_field(query)), None)


def demo_papers(query: str) -> list[Paper]:
    found = lookup(query)
    return [PAPERS[i] for i in found[1][3]] if found else []
