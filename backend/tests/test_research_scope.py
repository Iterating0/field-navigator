import asyncio

from app.config import Settings
from app.models.schemas import Paper
from app.services.literature_retriever import LiteratureRetriever
from app.services.research_scope import scope_mismatch, scope_qualification


def test_explicit_dimension_mismatch_is_blocked_but_target_and_mapping_are_not():
    field = 'one-dimensional non-Hermitian transport'
    assert scope_mismatch(field, None, 'Non-Bloch Chern bands')
    assert scope_mismatch(field, None, 'Two-dimensional skin effects')
    assert scope_mismatch(field, None, 'Lattice spectrum', 'We study a two-dimensional lattice.')
    assert scope_mismatch(field, None, 'One-dimensional chain', 'We compare two-dimensional systems.') is None
    assert scope_mismatch(field, None, 'Band theory in arbitrary dimensions') is None
    assert scope_mismatch(field, 'Compare one- and two-dimensional skin effects', 'Two-dimensional skin effects') is None
    assert scope_mismatch(field, 'Study topological pumping and Chern mapping', 'Chern bands') is None
    assert scope_mismatch('one-dimensional quantum Hall edges', None, 'Quantum Hall edge transport') is None
    assert scope_mismatch('一维非互易链', None, '二维非厄米模型')
    assert scope_mismatch(field, 'Only one-dimensional chains, not two-dimensional systems', 'Two-dimensional systems')


def test_species_gate_follows_exclusive_question_and_primary_subject():
    field = 'genome editing efficiency'
    assert scope_mismatch(field, 'Precise mammalian genome edits', 'Engineered editor in plants')
    assert scope_mismatch(field, 'Precise human genome edits', 'Editing efficiency in rice')
    assert scope_mismatch(field, 'Precise mammalian genome edits', 'Editing human and plant cells') is None
    assert scope_mismatch(field, 'Compare mammalian and plant editing', 'Editor in plants') is None
    assert scope_mismatch(field, None, 'Editor in plants') is None
    assert scope_mismatch(field, 'Precise mammalian genome edits', 'Editor in human cells',
                          'We compare the result with earlier plant studies.') is None
    assert scope_mismatch('哺乳动物基因编辑', None, '植物编辑器')
    assert scope_mismatch(field, 'Human genome edits, excluding plants', 'Editor in plants')
    assert scope_mismatch('哺乳动物基因编辑', '不涉及植物', '植物编辑器')
    assert scope_mismatch('RAG evaluation', 'Compare model ratings with human judges',
                          'RAG answers on a plant dataset') is None


def test_species_gate_covers_finite_non_mammal_taxa_and_quote_only_subjects():
    field = 'genome editing efficiency'
    question = 'Precise mammalian genome edits'
    for title in (
        'Genome editing in zebrafish',
        'Avian genome editing',
        'Chicken embryo editing',
        'Frog genome editing',
        'Xenopus genome editing',
        'Drosophila genome editing',
        'C. elegans genome editing',
    ):
        assert scope_mismatch(field, question, title)

    # An audited abstract quote can be the only available subject signal.
    assert scope_mismatch(field, question, '', 'We edit zebrafish embryos.')
    # A full abstract may mention mammalian background while the specific
    # subject remains another taxon; the quote-level call receives only the
    # exact quote and makes the conservative decision above.
    assert scope_mismatch(
        field, question, '',
        'Earlier mammalian studies provide context; here we edit zebrafish embryos.',
    ) is None
    assert scope_mismatch(field, question, 'Zebrafish genome editing',
                          'Earlier mammalian studies provide context.')

    # Positive multi-species requests remain eligible, while an explicit
    # exclusion keeps the mammalian gate strict.
    assert scope_mismatch(
        field, 'Compare mammalian and zebrafish genome edits',
        'Genome editing in zebrafish',
    ) is None
    assert scope_mismatch(
        field, 'Mammalian genome edits, excluding zebrafish',
        'Genome editing in zebrafish',
    )
    assert scope_mismatch(
        field, 'Mammalian genome edits, no fish',
        'Genome editing in zebrafish',
    )


def test_all_dimension_scope_forms_include_spatial_dimension_variants():
    field = 'one-dimensional non-Hermitian transport'
    assert scope_mismatch(field, None, 'Theory in arbitrary spatial dimensions') is None
    assert scope_mismatch(field, None, 'Theory in any spatial dim') is None
    assert scope_qualification(
        field, None, 'General theory', 'The model applies to arbitrary spatial dimensions.'
    )
    assert scope_qualification(
        field, None, 'General theory', 'The model applies to all spatial dims.'
    )


def test_layer_gate_keeps_target_and_comparative_questions():
    field = 'twisted bilayer graphene superconductivity'
    assert scope_mismatch(field, None, 'Twisted trilayer graphene superconductivity')
    assert scope_mismatch(field, None, 'Multilayer graphene superconductivity')
    assert scope_mismatch(field, None, 'Superconductivity in twisted bilayer graphene') is None
    assert scope_mismatch(field, 'Compare bilayer and trilayer devices', 'Trilayer graphene') is None
    assert scope_mismatch('双层石墨烯', None, '三层石墨烯超导')
    assert scope_mismatch(field, 'Bilayer, rather than trilayer', 'Trilayer graphene')


def test_retrieval_removes_conflicting_subject_before_model_assessment():
    class Planner:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'genome editing', 'alternative': ''}

    class Papers:
        async def search_papers(self, *args, **kwargs):
            return [Paper(id='plant', title='Enhanced genome editing in plants'),
                    Paper(id='human', title='Enhanced genome editing in human cells')]

    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), Planner()).retrieve(
        'genome editing efficiency', 40, research_question='Precise mammalian genome edits'))
    assert [paper.id for paper in result.papers] == ['human']
    assert any('物种范围冲突' in warning for warning in result.warnings)


def test_bilayer_scope_checks_exclusive_abstract_subject_without_blocking_comparisons():
    field = 'twisted bilayer graphene superconductivity'
    generic_title = 'Superconductivity in twisted graphene devices'
    assert scope_mismatch(field, None, generic_title,
                          'We measure a trilayer device under gate control.')
    assert scope_mismatch(field, None, '', 'We measure superconductivity in multilayer graphene.')
    assert scope_mismatch(field, None, generic_title,
                          'We compare bilayer and trilayer devices.') is None
    assert scope_mismatch(field, 'Compare bilayer and trilayer superconductivity', generic_title,
                          'We measure a trilayer device.') is None
    assert scope_mismatch(field, None, 'Twisted bilayer graphene superconductivity',
                          'We compare our system with earlier multilayer devices.') is None


def test_scope_gate_uses_verified_identity_instead_of_uncorrected_index_title():
    class Planner:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'genome editing', 'alternative': ''}

    class Papers:
        async def search_papers(self, *args, **kwargs):
            return [Paper(id='work', title='Wrong index title about plants')]

    class Metadata:
        async def verify(self, papers):
            return [papers[0].model_copy(update={'title': 'Editing in human cells'})], []

    retriever = LiteratureRetriever(Settings(_env_file=None), Papers(), Planner())
    retriever.metadata_verifier = Metadata()
    result = asyncio.run(retriever.retrieve('genome editing efficiency', 40,
                                          research_question='Precise mammalian genome edits'))
    assert result.papers[0].title == 'Editing in human cells'


def test_general_dimensional_theory_retained_with_one_dimensional_scope_warning():
    class Planner:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'non-Hermitian skin effect', 'alternative': ''}

    class Papers:
        async def search_papers(self, *args, **kwargs):
            return [Paper(id='general', title='Topology of non-Hermitian spectra',
                          abstract='We derive a theoretical result in arbitrary dimensions.')]

    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), Planner()).retrieve(
        'one-dimensional non-Hermitian skin effect', 40))
    assert [paper.id for paper in result.papers] == ['general']
    assert any('任意维度的理论' in warning for warning in result.warnings)
    assert scope_qualification('one-dimensional chains', None, 'One-dimensional chains') is None
    assert scope_qualification('arbitrary dimensions', None, 'General theory', 'all dimensions') is None
    assert scope_qualification('one-dimensional chains', None, 'Restricted theory', 'not all dimensions') is None
