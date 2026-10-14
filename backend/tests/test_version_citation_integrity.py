from app.models.schemas import Paper
from app.services.paper_quality import quality_filter_and_dedupe


def test_missing_published_count_cannot_inherit_an_untrusted_preprint_count():
    paper = dict(title='A sufficiently specific canonical research object study',
                 authors=['Public Author'], year=2020)
    result = quality_filter_and_dedupe([
        Paper(id='published', doi='10.1234/published', work_version='publishedVersion',
              citation_count=None, **paper),
        Paper(id='preprint', work_version='submittedVersion', citation_count=99999, **paper),
    ])
    assert len(result) == 1 and result[0].id == 'published'
    assert result[0].citation_count is None


def test_merged_preprint_identifier_remains_available_for_original_source_checks():
    paper = dict(title='A sufficiently specific canonical research object study',
                 authors=['Public Author'], year=2020)
    result = quality_filter_and_dedupe([
        Paper(id='published', doi='10.1234/published', work_version='publishedVersion', **paper),
        Paper(id='preprint', doi='10.48550/arxiv.2005.11401', work_version='submittedVersion', **paper),
    ])
    assert 'https://doi.org/10.48550/arxiv.2005.11401' in result[0].source_record_ids
