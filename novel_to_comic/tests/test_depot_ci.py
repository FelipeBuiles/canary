"""Release contracts for native Depot CI, without provider or deploy calls."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / '.depot/workflows/ci.yml').read_text())
JOBS = WORKFLOW['jobs']


def test_github_only_provides_events_and_checks():
    assert not list((ROOT / '.github/workflows').glob('*.yml'))
    assert WORKFLOW[True]['push']['branches'] == ['main']
    assert WORKFLOW[True]['pull_request']['branches'] == ['main']
    for job in JOBS.values():
        runner = job['runs-on']
        if isinstance(runner, str):
            assert runner.startswith('depot-')
        else:
            assert runner['image'].startswith('6ntrqswcbt.registry.depot.dev/')


def test_deployment_waits_for_all_checks_and_production_image():
    assert set(JOBS['deploy']['needs']) == {
        'backend', 'web', 'gateway', 'tooling', 'database', 'release_image',
    }
    assert 'needs' not in JOBS['release_image']  # Build alongside tests.
    for name in ('release_image', 'deploy'):
        condition = (
            "github.ref == 'refs/heads/main' && "
            "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
        )
        if name == 'deploy':
            condition = "vars.CANARY_DEPLOY_TARGET == 'lightsail' && " + condition
        assert JOBS[name]['if'] == condition
        assert JOBS[name]['environment'] == 'production'
    assert JOBS['docker']['if'] == "github.event_name == 'pull_request'"


def test_deploy_and_smoke_test_use_same_immutable_digest():
    image = JOBS['release_image']
    assert image['outputs']['image'] == 'registry.depot.dev/js338b6zll@${{ steps.image.outputs.digest }}'
    smoke = next(s for s in image['steps'] if s.get('name') == 'Smoke test release image')
    assert smoke['env']['IMAGE'] == image['outputs']['image']
    deploy = next(s for s in JOBS['deploy']['steps'] if s.get('name') == 'Deploy exact release image')
    assert deploy['env']['CANARY_RELEASE_IMAGE'] == '${{ needs.release_image.outputs.image }}'
    assert deploy['run'] == 'python3 scripts/deploy_lightsail.py'
    assert 'FLY_API_TOKEN' not in str(WORKFLOW)
    assert 'CANARY_OPS_TOKEN' not in str(WORKFLOW)
    assert 'skip_drain' not in str(WORKFLOW)


def test_deployment_lock_and_drain_order():
    deploy = JOBS['deploy']
    assert deploy['concurrency']['group'] == 'production-deploy'
    assert deploy['concurrency']['cancel-in-progress'] is False
    names = [s.get('name', '') for s in deploy['steps']]
    assert names.index('Obtain scoped AWS firewall access') < names.index('Deploy exact release image')
    assert names.index('Deploy exact release image') < names.index('Record deployed release')
    release = next(s for s in deploy['steps'] if s.get('name') == 'Deploy exact release image')
    assert release['env']['CANARY_RELEASE_VERSION'] == '${{ github.sha }}'
    assert deploy['permissions']['id-token'] == 'write'


def test_pr_checks_never_reference_production_secrets():
    for name in ('backend', 'web', 'docker', 'gateway', 'tooling', 'database'):
        assert 'secrets.' not in str(JOBS[name])
        assert 'continue-on-error' not in JOBS[name]
    assert WORKFLOW['concurrency']['cancel-in-progress'] == "${{ github.event_name == 'pull_request' }}"
