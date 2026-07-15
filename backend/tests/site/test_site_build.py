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

REGISTRY = """\
| ID | Title | Spec | Status | Milestone |
|----|-------|------|--------|-----------|
| FRG-SER-019 | Trades never suppress single-issue wanted | ser | implemented | M3 |
| FRG-TST-001 | Fixture requirement with tests | tst | implemented | M1 |
| FRG-TST-002 | Fixture requirement without tests | tst | approved | B |
| FRG-TST-003 | Withdrawn fixture requirement | tst | withdrawn | B |
"""

MATRIX = """\
| ID | Status | Milestone | Spec | Tests | Commits |
|----|--------|-----------|------|-------|---------|
| FRG-SER-019 | implemented | M3 | ser | backend/tests/library/test_a.py, backend/tests/library/test_b.py | abc1234, def5678 |
| FRG-TST-001 | implemented | M1 | tst | backend/tests/test_c.py | 1111111 |
| FRG-TST-002 | approved | B | tst | — | — |
| FRG-TST-003 | withdrawn | B | tst | — | — |
"""

CHANGELOG = """\
# Changelog

Intro text.

## [v0.1.1] — 2026-02-02

### Fixed
- **A fixture fix** (FRG-TST-001): with `code` and a
  continuation line.

## [v0.1.0] — 2026-01-01

First fixture release.

### Added
- A fixture feature (FRG-SER-019).
"""

RISKS = """\
| ID | Description | STRIDE | Component | L | I | Status | Current mitigation | Source |
|----|-------------|--------|-----------|---|---|--------|--------------------|--------|
| RISK-001 | Fixture risk one. | DoS | API | M | H | Mitigated (fixture) | Something. | analysis |
| RISK-002 | Fixture risk two. | Spoofing | UI | L | L | Open (target: B) | Nothing yet. | analysis |
"""


def make_repo(root: Path, changelog: str = CHANGELOG, tags=('v0.1.0', 'v0.1.1'),
              license_text: str = GPL_HEADER) -> Path:
    (root / 'docs/traceability').mkdir(parents=True)
    (root / 'docs/security').mkdir(parents=True)
    (root / 'docs/assets').mkdir(parents=True)
    (root / 'docs/readme-assets').mkdir(parents=True)
    (root / 'docs/traceability/requirements-registry.md').write_text(REGISTRY)
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
    site_build.build(root, out)
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
    # 3 live requirements (one withdrawn excluded), 2 with tagged tests.
    assert '>3</div><div class="stat-l">requirements in the registry' in index
    assert '>2 of 3</div><div class="stat-l">requirements with tagged tests' in index
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
        site_build.build(root, out)
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
    assert 'FRG-SER-019' in index
    assert 'Trades never suppress single-issue wanted' in index
    assert 'openspec/specs/ser/spec.md' in index          # from matrix spec cell
    assert 'backend/tests/library/test_a.py +1 more' in index
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


@pytest.mark.req("FRG-SITE-003")
def test_untagged_changelog_entry_fails_the_build(tmp_path, capsys):
    root = make_repo(tmp_path / 'repo', tags=('v0.1.0',))  # v0.1.1 entry, no tag
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out')
    assert 'v0.1.1' in capsys.readouterr().err


@pytest.mark.req("FRG-SITE-004")
def test_every_indexed_artifact_exists(tmp_path):
    root = make_repo(tmp_path / 'repo')
    (root / 'docs/security/threat-model.md').unlink()
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out')


@pytest.mark.req("FRG-SITE-004")
def test_nonexistent_evidence_is_not_claimed(built):
    pages, _ = built
    for name, content in pages.items():
        low = site_build.ABSENCE_SECTION_RE.sub('', content).lower()
        for phrase in ('penetration test', 'pentest', 'sbom', 'acceptance report',
                       'enforced in ci'):
            assert phrase not in low, f'{phrase!r} claimed in {name}'


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
        site_build.build(root, tmp_path / 'out')


@pytest.mark.req("FRG-SITE-004")
def test_coverage_breakdown_is_derived_by_status(built):
    pages, _ = built
    trust = pages['trust.html']
    # Fixture matrix: 2 implemented (both tested), 1 approved (untested),
    # 0 active process rules.
    assert '2 of 2' in trust
    assert 'implemented requirements with tagged tests' in trust
    assert 'approved, not yet built' in trust
    assert '0 of 0' in trust and 'process rules machine-tested' in trust


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
        site_build.build(root, tmp_path / 'out')


@pytest.mark.req("FRG-SITE-004")
def test_coverage_metric_replaces_test_count(built):
    pages, _ = built
    index = pages['index.html']
    assert 'requirements with tagged tests' in index
    assert 'automated tests' not in index.lower()


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
        site_build.build(root, tmp_path / 'out')


@pytest.mark.req("FRG-SITE-006")
def test_banned_phrase_in_source_fails_the_build(tmp_path, capsys):
    poisoned = CHANGELOG.replace('A fixture feature', 'An acceptance report')
    root = make_repo(tmp_path / 'repo', changelog=poisoned)
    with pytest.raises(SystemExit):
        site_build.build(root, tmp_path / 'out')
    assert 'acceptance report' in capsys.readouterr().err


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
