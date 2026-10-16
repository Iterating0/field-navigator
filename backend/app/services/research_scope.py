"""Reject a few explicit research-scope contradictions before model assessment.

These checks are conservative metadata gates, not a general semantic classifier.
They contain no paper names, authors, DOI lists, or benchmark identifiers. An
unknown scope is left to the independent audit; cross-system questions and
papers whose title explicitly includes the target remain eligible for it.
"""
from __future__ import annotations

import re
import unicodedata


ONE_D = re.compile(r'\b(?:1[\s-]*d|one[\s-]+dimension(?:al)?|1[\s-]+dimensional)\b|一维')
OTHER_D = re.compile(r'\b(?:[23][\s-]*d|(?:two|three)[\s-]+dimensional|'
                     r'higher[\s-]+dimension(?:al|s)?|high[\s-]+dimensional)\b|二维|三维|高维')
ALL_D = re.compile(
    r'\b(?:arbitrary|any|all)(?:\s+spatial)?\s+(?:dims?|dimensions?)\b|'
    r'任意(?:空间)?维(?:度)?'
)
CHERN_SYSTEM = re.compile(r'\bchern\s+(?:bands?|insulators?)\b|\bquantum\s+hall\b|陈绝缘|量子霍尔')
DIMENSION_MAPPING = re.compile(r'\b(?:pump\w*|chern|quantum\s+hall|synthetic\s+dimension\w*|dimensional\s+mapping)\b'
                               r'|泵浦|泵送|合成维|维度映射|陈数|量子霍尔')
MAMMAL = re.compile(r'\b(?:mammals?|mammalian|humans?|mouse|mice)\b|哺乳|人类|人源|小鼠')
MAMMAL_ORGANISM = re.compile(r'\b(?:mammals?|mammalian|mouse|mice)\b|哺乳|小鼠')
BIOLOGICAL_TASK = re.compile(r'\b(?:genomes?|genes?|genetic|editing|dna|rna|cells?|proteins?)\b'
                             r'|基因|基因组|编辑|细胞|蛋白')
PLANT = re.compile(r'\b(?:plants?|rice|arabidopsis|maize|wheat)\b|植物|水稻|拟南芥|玉米|小麦')
NON_MAMMAL = re.compile(
    r'\b(?:zebrafish|danio\s+rerio|fish|fishes|birds?|avian|chicken|'
    r'amphibians?|frogs?|xenopus|invertebrates?|drosophila|worms?|'
    r'c\.?\s*elegans|caenorhabditis\s+elegans|plants?|rice|arabidopsis|'
    r'maize|wheat)\b|'
    r'斑马鱼|鱼类?|鸟类?|禽类?|鸡|两栖类?|青蛙|爪蟾|无脊椎动物?|果蝇|线虫|'
    r'植物|水稻|拟南芥|玉米|小麦'
)
BILAYER = re.compile(r'\b(?:bilayer|two[\s-]+layer)\b|双层|二层')
OTHER_LAYER = re.compile(r'\b(?:trilayer|multilayer|three[\s-]+layer|multi[\s-]+layer)\b|三层|多层')
EXCLUDED_PREFIX = re.compile(r'(?:\b(?:not|no|excluding|exclude|without|rather than|instead of)\s+'
                             r'(?:(?:a|the|any|in)\s+)?|(?:不包括|不含|不包含|排除|不要|不是|而非|不考虑|不涉及)\s*)$')


def _text(value: str | None) -> str:
    value = unicodedata.normalize('NFKC', value or '').casefold()
    return value.translate(str.maketrans({'–': '-', '—': '-', '‑': '-'}))


def _requested(pattern: re.Pattern, query: str) -> bool:
    # An explicitly excluded comparison does not widen the target scope.
    return any(not EXCLUDED_PREFIX.search(query[max(0, match.start() - 45):match.start()])
               for match in pattern.finditer(query))


def scope_mismatch(
    field: str,
    research_question: str | None,
    title: str,
    abstract: str | None = None,
) -> str | None:
    """Return a category only for explicit, exclusive scope conflicts.

    A 1D pump/Chern mapping or explicit cross-dimensional question is not
    exclusive 1D. A comparative human/plant or bi-/trilayer query is not
    exclusive either. Generic all-dimensional results are left to the audit.
    Main-study titles take precedence over incidental background comparisons.
    """
    query = _text(field + ' ' + (research_question or ''))
    subject = _text(title)
    metadata = subject + ' ' + _text(abstract)

    strict_one_d = (_requested(ONE_D, query) and not _requested(OTHER_D, query)
                    and not _requested(ALL_D, query) and not _requested(DIMENSION_MAPPING, query))
    if strict_one_d and not ONE_D.search(subject):
        if CHERN_SYSTEM.search(subject):
            return '维度范围冲突：Chern/量子霍尔主体不作为限定一维系统的直接证据'
        if OTHER_D.search(subject) and not ALL_D.search(subject):
            return '维度范围冲突：主体为高维系统'
        if (OTHER_D.search(metadata) and not ONE_D.search(metadata)
                and not ALL_D.search(metadata)):
            return '维度范围冲突：元数据仅明确高维系统'

    strict_mammal = (_requested(MAMMAL, query) and not _requested(NON_MAMMAL, query)
                     and (_requested(MAMMAL_ORGANISM, query) or BIOLOGICAL_TASK.search(query)))
    if strict_mammal:
        # A title with an explicit taxon is the primary-study subject.  If the
        # title is generic, an abstract-only excerpt can still be the audited
        # subject; requiring mammal evidence in that excerpt prevents a bare
        # zebrafish/fish result from passing a mammalian question.  Full
        # abstracts that mention both a mammal background and another taxon are
        # left for the quote-level gate to resolve.
        title_has_mammal = bool(MAMMAL.search(subject))
        title_has_other_taxon = bool(NON_MAMMAL.search(subject))
        abstract_has_mammal = bool(MAMMAL.search(_text(abstract)))
        abstract_has_other_taxon = bool(NON_MAMMAL.search(_text(abstract)))
        if title_has_other_taxon and not title_has_mammal:
            label = '植物' if PLANT.search(subject) else '非哺乳动物'
            return f'物种范围冲突：主体为{label}，不能直接支持限定哺乳动物的问题'
        if (not title_has_mammal and abstract_has_other_taxon
                and not abstract_has_mammal):
            label = '植物' if PLANT.search(abstract or '') else '非哺乳动物'
            return f'物种范围冲突：核对摘录主体为{label}，不能直接支持限定哺乳动物的问题'

    strict_bilayer = _requested(BILAYER, query) and not _requested(OTHER_LAYER, query)
    if strict_bilayer and OTHER_LAYER.search(subject) and not BILAYER.search(subject):
        return '层数范围冲突：主体不是双层系统'
    if (strict_bilayer and not BILAYER.search(subject)
            and OTHER_LAYER.search(metadata) and not BILAYER.search(metadata)):
        return '层数范围冲突：元数据仅明确三层或多层系统'
    return None


def scope_qualification(
    field: str, research_question: str | None, title: str, abstract: str | None = None,
) -> str | None:
    """Keep general-dimensional theory eligible while exposing its scope boundary."""
    query = _text(field + ' ' + (research_question or ''))
    metadata = _text(title + ' ' + (abstract or ''))
    if (_requested(ONE_D, query) and not _requested(OTHER_D, query)
            and not _requested(ALL_D, query) and _requested(ALL_D, metadata)):
        return '题录元数据包含任意维度的理论；用于一维问题需核对模型与适用条件，不能当作一维实验结果'
    return None
