"""Site generator tests (FRG-SITE-001..006).

Runs site/build.py against a fixture repository so every asserted fact has a
known source, plus text-level checks on the real Pages workflow.
"""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

spec = importlib.util.spec_from_file_location('site_build', REPO_ROOT / 'site' / 'build.py')
site_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_build)

GPL_HEADER = (
    '                    GNU GENERAL PUBLIC LICENSE\n'
    '                       Version 3, 29 June 2007\n'
)

# Fixtures use only synthetic, unallocated IDs (FRG-TST-*, FRG-PROC-90x,
# FRG-SER-901) so this test file's embedded constants never collide with a real
# requirement ID — tools/trace.py tags tests by substring, so a real ID here
# would falsely credit this file as that requirement's test. The exemplar is a
# fixture ID supplied through a fixture site.toml (config_dir), not the real
# exemplar the shipped site.toml points at.
EXEMPLAR = 'FRG-TST-001'

REGISTRY = """\
| ID | Title | Spec | Status | Milestone |
|----|-------|------|--------|-----------|
| FRG-TST-001 | Fixture requirement with tests | tst | implemented | M1 |
| FRG-TST-002 | Fixture requirement without tests | tst | approved | B |
| FRG-TST-003 | Withdrawn fixture requirement | tst | withdrawn | B |
| FRG-PROC-901 | Fixture process rule machine-tested | dev-process | active | — |
| FRG-PROC-902 | Fixture process rule hook-enforced | dev-process | active | — |
"""

MATRIX = """\
| ID | Status | Milestone | Spec | Tests | Commits |
|----|--------|-----------|------|-------|---------|
| FRG-TST-001 | implemented | M1 | tst | backend/tests/test_a.py, backend/tests/test_b.py | abc1234, def5678 |
| FRG-TST-002 | approved | B | tst | — | — |
| FRG-TST-003 | withdrawn | B | tst | — | — |
| FRG-PROC-901 | active | — | dev-process | backend/tests/test_proc.py | 1111111 |
| FRG-PROC-902 | active | — | dev-process | — | — |
"""

CHANGELOG = """\
# Changelog

Intro text.

## [v0.1.1] — 2026-02-02

### Fixed
- **A fixture fix** (FRG-TST-001): with `code` and a
  continuation line.

```yaml
environment:
  - KEY=value
```

## [v0.1.0] — 2026-01-01

First fixture release.

### Added
- A fixture feature (FRG-TST-002).
"""

RISKS = """\
| ID | Description | STRIDE | Component | L | I | Status | Current mitigation | Source |
|----|-------------|--------|-----------|---|---|--------|--------------------|--------|
| RISK-001 | Fixture risk one. | DoS | API | M | H | Mitigated (fixture) | Something. | analysis |
| RISK-002 | Fixture risk two. | Spoofing | UI | L | L | Open (target: B) | Nothing yet. | analysis |
"""

SITE_TOML = f"""\
[site]
title = "fixture site"
description = "fixture description"
repo_url = "https://github.com/AdrianRossouw/foragerr"
releases_url = "https://github.com/AdrianRossouw/foragerr/releases"

[hero]
exemplar_requirement = "{EXEMPLAR}"
"""


def make_repo(root: Path, changelog: str = CHANGELOG, tags=('v0.1.0', 'v0.1.1'),
              license_text: str = GPL_HEADER, registry: str = REGISTRY) -> Path:
    (root / 'config').mkdir(parents=True)
    (root / 'config/site.toml').write_text(SITE_TOML)
    (root / 'docs/traceability').mkdir(parents=True)
    (root / 'docs/security').mkdir(parents=True)
    (root / 'docs/assets').mkdir(parents=True)
    (root / 'docs/readme-assets').mkdir(parents=True)
    (root / 'docs/traceability/requirements-registry.md').write_text(registry)
    (root / 'docs/traceability/matrix.md').write_text(MATRIX)
    (root / 'CHANGELOG.md').write_text(changelog)
    (root / 'docs/security/risk-register.md').write_text(RISKS)
    (root / 'docs/security/threat-model.md').write_text('# Threat model\n')
    (root / 'docs/security/soup-register.md').write_text('# SOUP\n')
    (root / 'docs/security/known-anomalies.md').write_text('# Anomalies\n')
    (root / 'LICENSE').write_text(license_text)
    (root / 'docs/process').mkdir(parents=True)
    (root / 'docs/manual').mkdir(parents=True)
    (root / 'docs/process/commit-standard.md').write_text('# Commit standard\n')
    (root / 'docs/manual/index.md').write_text('# Manual\n')
    (root / 'docs/security/history-scan.md').write_text('# History scan\n')
    (root / 'docs/roadmap.md').write_text('# Roadmap\n')
    (root / 'openspec/specs/dev-process').mkdir(parents=True)
    (root / 'openspec/specs/dev-process/spec.md').write_text('# dev-process\n')
    for name, approved in (('2026-01-01-first', True), ('2026-01-02-second', True),
                           ('2026-01-03-unapproved', False)):
        d = root / 'openspec/changes/archive' / name
        d.mkdir(parents=True)
        body = '# p\n\n## Approval\n\nApproved.\n' if approved else '# p\n'
        (d / 'proposal.md').write_text(body)
    (root / 'docs/assets/foragerr-mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    for shot, _ in site_build.PRODUCT_SHOTS:
        (root / 'docs/readme-assets' / shot).write_bytes(b'\x89PNG-fixture')
    run = lambda *a: subprocess.run(
        ['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *a],
        check=True, capture_output=True)
    run('init', '-q')
    run('commit', '--allow-empty', '-q', '-m', 'fixture')
    for tag in tags:
        run('tag', tag)
    return root


def build(root: Path, out: Path):
    site_build.build(root, out, config_dir=root / 'config')
    return {p.name: p.read_text() for p in out.glob('*.html')}


@pytest.fixture()
def built(tmp_path):
    root = make_repo(tmp_path / 'repo')
    out = tmp_path / 'out'
    return build(root, out), out


@pytest.mark.req("FRG-SITE-001")
def test_facts_track_the_source_artifacts(built):
    pages, _ = built
    index = pages['index.html']
    # 4 live requirements (one withdrawn excluded); the 1 implemented one tested.
    assert '>4</div><div class="stat-l">requirements in the registry' in index
    assert ('>1 of 1</div><div class="stat-l">implemented requirements have '
            'tagged tests') in index
    assert '>2</div><div class="stat-l">tagged releases' in index
    assert '>2</div><div class="stat-l">risks tracked in the register' in index
    # No other numerals leak into stats: the values above came from fixtures.
    assert 'v0.1.1' in pages['timeline.html'] and 'v0.1.0' in pages['timeline.html']


@pytest.mark.req("FRG-SITE-001")
def test_missing_source_artifact_fails_without_output(tmp_path, capsys):
    root = make_repo(tmp_path / 'repo')
    (root / 'CHANGELOG.md').unlink()
    out = tmp_path / 'out'
    with pytest.raises(SystemExit) as exc:
        site_build.build(root, out, config_dir=root / 'config')
    assert exc.value.code == 1
    assert 'CHANGELOG' in capsys.readouterr().err
    assert not out.exists(), 'failing build must write nothing'


@pytest.mark.req("FRG-SITE-002")
def test_five_pages_with_shared_navigation(built):
    pages, _ = built
    names = {'index.html', 'method.html', 'timeline.html', 'trust.html', 'product.html'}
    assert set(pages) == names
    for name, content in pages.items():
        for other in names:
            assert f'href="{other}"' in content, f'{name} missing nav link to {other}'


@pytest.mark.req("FRG-SITE-002")
def test_trace_card_is_real(built):
    pages, _ = built
    index = pages['index.html']
    assert 'FRG-TST-001' in index
    assert 'Fixture requirement with tests' in index
    assert 'openspec/specs/tst/spec.md' in index          # from matrix spec cell
    assert 'backend/tests/test_a.py +1 more' in index
    assert 'abc1234, def5678' in index


@pytest.mark.req("FRG-SITE-002")
def test_honesty_callout_present(built):
    pages, _ = built
    method = pages['method.html']
    assert 'How to weigh this' in method
    assert 'no human has read every line' in method
    assert 'Discipline is the point; perfection is not the claim.' in method


@pytest.mark.req("FRG-SITE-003")
def test_releases_mirror_the_changelog(built):
    pages, _ = built
    tl = pages['timeline.html']
    assert tl.count('class="card release"') == 2
    assert tl.index('v0.1.1') < tl.index('v0.1.0'), 'newest first'
    assert '2026-02-02' in tl and '2026-01-01' in tl
    assert '<strong>A fixture fix</strong>' in tl
    assert '<code>code</code>' in tl
    assert 'continuation line' in tl
    # Code fences render as a <pre> block, not mangled list items.
    assert '<pre class="rel-code">' in tl and 'KEY=value' in tl
    assert 'environment: - KEY=value' not in tl


@pytest.mark.req("FRG-SITE-003")
def test_untagged_changelog_entry_fails_the_build(tmp_path, capsys):
    root = make_repo(tmp_path / 'repo', tags=('v0.1.0',))  # v0.1.1 entry, no tag
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')
    assert 'v0.1.1' in capsys.readouterr().err


@pytest.mark.req("FRG-SITE-004")
def test_every_indexed_artifact_exists(tmp_path):
    root = make_repo(tmp_path / 'repo')
    (root / 'docs/security/threat-model.md').unlink()
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')


@pytest.mark.req("FRG-SITE-004")
def test_nonexistent_evidence_is_not_claimed(built):
    pages, _ = built
    for name, content in pages.items():
        # Match scan_output's authored-copy view: strip both the absence section
        # and generated source-artifact passthrough.
        authored = site_build.GENERATED_SECTION_RE.sub(
            '', site_build.ABSENCE_SECTION_RE.sub('', content)).lower()
        for phrase in ('penetration test', 'pentest', 'sbom', 'acceptance report',
                       'enforced in ci'):
            assert phrase not in authored, f'{phrase!r} claimed in {name}'


@pytest.mark.req("FRG-SITE-004")
def test_governance_cards_render_with_derived_approval_count(built):
    pages, _ = built
    trust = pages['trust.html']
    assert 'Process &amp; governance' in trust
    for path in ('openspec/specs/dev-process/spec.md',
                 'docs/process/commit-standard.md',
                 'openspec/changes/archive/', 'docs/manual/',
                 'docs/security/history-scan.md'):
        assert path in trust, f'governance card missing: {path}'
    assert '2 of 3 approved' in trust  # from the fixture archive


@pytest.mark.req("FRG-SITE-004")
def test_missing_governance_artifact_fails_the_build(tmp_path):
    root = make_repo(tmp_path / 'repo')
    (root / 'docs/security/history-scan.md').unlink()
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')


@pytest.mark.req("FRG-SITE-004")
def test_coverage_breakdown_is_derived_by_status(built):
    pages, _ = built
    trust = pages['trust.html']
    # Fixture matrix: 1 implemented (tested), 1 approved (untested),
    # 2 process rules (PROC-901 tested, PROC-902 hook-enforced).
    assert '1 of 1' in trust
    assert 'implemented requirements with tagged tests' in trust
    assert 'approved, not yet built' in trust
    assert '1 of 2' in trust and 'process rules machine-tested' in trust


@pytest.mark.req("FRG-SITE-004")
def test_absences_stated_only_in_absence_section(built):
    pages, _ = built
    trust = pages['trust.html']
    sections = site_build.ABSENCE_SECTION_RE.findall(trust)
    assert len(sections) == 1, 'exactly one dedicated absence section'
    absence = sections[0].lower()
    assert 'penetration test' in absence
    assert 'not in place yet' in absence
    # Every absence entry cites an existing committed document.
    for _, _, cite in site_build.ABSENCES:
        assert cite in sections[0]
    # The phrases live nowhere else on any page.
    for name, content in pages.items():
        assert 'penetration test' not in \
            site_build.ABSENCE_SECTION_RE.sub('', content).lower(), name


@pytest.mark.req("FRG-SITE-006")
def test_absence_citation_must_exist(tmp_path):
    root = make_repo(tmp_path / 'repo')
    (root / 'docs/roadmap.md').unlink()  # cited by the pentest absence entry
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')


@pytest.mark.req("FRG-SITE-004")
def test_coverage_metric_replaces_test_count(built):
    pages, _ = built
    index = pages['index.html']
    assert 'implemented requirements have tagged tests' in index
    assert 'automated tests' not in index.lower()
    # No all-requirements ratio: fixture has 4 live requirements, and no
    # "of 4" coverage figure may appear anywhere in the strip.
    assert 'of 4</div>' not in index


@pytest.mark.req("FRG-SITE-006")
def test_license_and_links_are_accurate(built):
    pages, _ = built
    assert 'GPL-3.0' in pages['index.html']
    for content in pages.values():
        assert 'https://github.com/AdrianRossouw/foragerr' in content


@pytest.mark.req("FRG-SITE-006")
def test_unrecognized_license_fails_the_build(tmp_path):
    root = make_repo(tmp_path / 'repo', license_text='MIT License\n\nPermission is hereby granted...')
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')


@pytest.mark.req("FRG-SITE-006")
def test_everywhere_phrase_in_source_fails_the_build(tmp_path, capsys):
    # A positioning phrase must fail even in generated source-artifact passthrough.
    poisoned = CHANGELOG.replace('A fixture feature', 'Pure piracy tooling')
    root = make_repo(tmp_path / 'repo', changelog=poisoned)
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')
    assert 'piracy' in capsys.readouterr().err


@pytest.mark.req("FRG-SITE-004")
def test_claims_phrase_in_generated_passthrough_is_allowed(tmp_path):
    # A truthful mention of an evidence word inside a source artifact (rendered
    # in a data-generated region) must NOT break the build.
    risks = RISKS.replace('Fixture risk one.',
                          'No penetration test has been performed yet.')
    root = make_repo(tmp_path / 'repo')
    (root / 'docs/security/risk-register.md').write_text(risks)
    site_build.build(root, tmp_path / 'out', config_dir=root / 'config')  # no raise


@pytest.mark.req("FRG-SITE-006")
def test_two_tier_scan_rules(tmp_path):
    banned = {'everywhere': ['piracy'], 'claims-only': ['pentest']}
    ok = ('<section data-absence>no pentest here</section>'
          '<section data-generated>risk row mentions pentest</section>'
          '<p>clean authored copy</p>'
          'https://github.com/AdrianRossouw/foragerr GPL-3.0')
    # Authored 'pentest' outside the exempt regions must fail.
    with pytest.raises(SystemExit):
        site_build.scan_output({'index.html': ok + '<p>pentest in authored copy</p>'},
                               banned, 'GPL-3.0',
                               'https://github.com/AdrianRossouw/foragerr')
    # 'piracy' anywhere — even inside a data-generated region — must fail.
    with pytest.raises(SystemExit):
        site_build.scan_output(
            {'index.html': ok + '<section data-generated>piracy</section>'},
            banned, 'GPL-3.0', 'https://github.com/AdrianRossouw/foragerr')
    # The clean page passes.
    site_build.scan_output({'index.html': ok}, banned, 'GPL-3.0',
                           'https://github.com/AdrianRossouw/foragerr')


@pytest.mark.req("FRG-SITE-001")
def test_out_dir_guard_refuses_repo_root(tmp_path):
    root = make_repo(tmp_path / 'repo')
    with pytest.raises(SystemExit):
        site_build.build(root, root, config_dir=root / 'config')  # --out == repo root
    assert (root / 'CHANGELOG.md').is_file(), 'repo must be untouched'


@pytest.mark.req("FRG-SITE-004")
def test_non_process_active_requirement_fails(tmp_path, capsys):
    reg = REGISTRY.replace(
        '| FRG-PROC-902 | Fixture process rule hook-enforced | dev-process | active | — |',
        '| FRG-SER-901 | A feature wrongly left active | ser | active | M1 |')
    root = make_repo(tmp_path / 'repo', registry=reg)
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')
    assert 'FRG-SER-901' in capsys.readouterr().err


@pytest.mark.req("FRG-SITE-004")
def test_archive_missing_proposal_fails(tmp_path):
    root = make_repo(tmp_path / 'repo')
    (root / 'openspec/changes/archive/2026-01-01-first/proposal.md').unlink()
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')


@pytest.mark.req("FRG-SITE-003")
def test_malformed_release_heading_fails(tmp_path, capsys):
    # A release-like heading that doesn't match the required form fails loudly
    # rather than silently dropping the release.
    bad = CHANGELOG.replace('## [v0.1.1] — 2026-02-02',
                            '## [v0.1.1] - 2026-02-02')  # plain hyphen
    root = make_repo(tmp_path / 'repo', changelog=bad)
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out', config_dir=root / 'config')
    assert 'v0.1.1' in capsys.readouterr().err


@pytest.mark.req("FRG-SITE-004")
def test_blank_matrix_test_cell_not_counted_as_tested(tmp_path):
    # An empty (not "—") Tests cell must not be counted as a tagged test.
    matrix = MATRIX.replace(
        '| FRG-TST-002 | approved | B | tst | — | — |',
        '| FRG-TST-002 | implemented | B | tst |  |  |')
    reg = REGISTRY.replace(
        '| FRG-TST-002 | Fixture requirement without tests | tst | approved | B |',
        '| FRG-TST-002 | Fixture requirement without tests | tst | implemented | B |')
    root = make_repo(tmp_path / 'repo', registry=reg)
    (root / 'docs/traceability/matrix.md').write_text(matrix)
    pages = build(root, tmp_path / 'out')
    # 2 implemented now, only 1 tested → "1 of 2", never "2 of 2".
    assert '1 of 2' in pages['trust.html']
    assert '2 of 2' not in pages['trust.html']


WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'pages.yml'


@pytest.mark.req("FRG-SITE-005")
def test_workflow_is_pinned_and_least_privilege():
    text = WORKFLOW.read_text()
    uses = re.findall(r'uses:\s*(\S+)', text)
    assert uses, 'workflow declares no actions'
    for ref in uses:
        assert re.fullmatch(r'[\w./-]+@[0-9a-f]{40}', ref), f'unpinned action: {ref}'
    perms = re.search(r'permissions:\n((?:\s+\S+: \S+\n)+)', text)
    assert perms, 'workflow declares no permissions block'
    granted = dict(l.strip().split(': ') for l in perms.group(1).strip().splitlines())
    assert granted == {'contents': 'read', 'pages': 'write', 'id-token': 'write'}


@pytest.mark.req("FRG-SITE-005")
def test_workflow_deploys_on_push_to_main():
    text = WORKFLOW.read_text()
    assert re.search(r'on:\n\s+push:\n\s+branches: \[main\]', text)
    assert 'site/build.py' in text
    assert 'actions/deploy-pages' in text
