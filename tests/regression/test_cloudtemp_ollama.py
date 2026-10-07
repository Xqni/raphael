"""Regression: profile cloud_temp must NEVER start or call Ollama
(AGENT_RULES §6, WAVES global constraints, config.yaml local_model.enabled).

- config gates (static, must hold NOW);
- runtime: a full job through the router must produce ZERO requests to the
  ollama URL (counting mock), even though the provider object exists;
- supervisor/systemd bring-up must not start ollama under cloud_temp
  (tripwires — currently unconditional; requests filed to infra).
"""
import re
from pathlib import Path


from harness.wssession import WSSession

REPO = Path.cwd()


def _config_text() -> str:
    return (REPO / 'config.yaml').read_text()


def test_config_cloud_temp_disables_local_models():
    text = _config_text()
    m = re.search(r'^profile:\s*(\S+)', text, re.M)
    assert m and m.group(1) == 'cloud_temp'
    lm = re.search(r'^\s*enabled:\s*(\S+)', text[text.find('local_model:'):],
                   re.M)
    assert lm and lm.group(1) == 'false', 'local_model.enabled must be false'
    chain = re.search(r'^\s*chain:\s*\[([^\]]+)\]', text, re.M)
    assert 'ollama' not in chain.group(1)
    # profile local keeps the ollama path available for Wave 6 (never deleted)
    assert 'ollama' in text[text.find('profiles:'):]


def test_router_never_touches_ollama_url_during_a_job(client, qa_token,
                                                      router_to_mock):
    """chain=[zen_free] end-to-end: the ollama base URL (pointed at a
    counting mock path) receives zero requests — local models are not even
    probed under cloud_temp."""
    router_to_mock.push({'content': 'cloud reply only'})
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'say something wise about clouds',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done', timeout=15)
        assert done['text'] == 'cloud reply only'
    ollama_hits = [r for r in router_to_mock.requests
                   if r['path'].startswith('/ollama')]
    assert ollama_hits == [], ollama_hits
    assert router_to_mock.completions_count >= 1   # it really went to zen mock


# PINNED STRICT 2026-10-07 (was xfail): infra landed the profile gate —
# supervisor only starts ollama when the profile/local_model allows it
# (request qa-security -> infra ollama-profile-gate).
def test_supervisor_gates_ollama_start_on_profile():
    src = (REPO / 'supervisor' / 'main.py').read_text()
    # find the ollama start block and require a profile/enabled gate nearby
    m = re.search(r'systemctl_action\([^)]*["\']start["\'][^)]*ollama_unit|'
                  r'ollama_unit[^)]*["\']start["\']', src, re.S)
    assert m, 'ollama start call not found (now gated?)'
    window = src[max(0, m.start() - 1500):m.start()]
    assert re.search(r'cloud_temp|local_model|profile|enabled', window, re.I), \
        'ollama start is unconditional (no profile/enabled gate above it)'


# PINNED STRICT 2026-10-07 (was xfail): infra removed the ollama pull-in
# from the unit (request qa-security -> infra ollama-profile-gate).
def test_systemd_unit_does_not_want_ollama():
    unit = (REPO / 'brain' / 'raphael-brain.service').read_text()
    active = [ln for ln in unit.splitlines()
              if ln.strip().startswith(('Wants=', 'After='))]
    assert not any('ollama' in ln and not ln.strip().startswith('#')
                   for ln in active), active
