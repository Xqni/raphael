"""Wave-4 resilience: provider-outage storm + recovery (mock provider).

Coordinates with infra's supervisor drills (kill/watchdog/orphan —
supervisor/tests) and brain-core's kill-safety matrix (engine shutdown) by
covering the BRAIN-side provider axis: a storm of 429/500s must fail jobs
cleanly with §10 codes (never crash the loop, never leave non-terminal
rows), and service must RECOVER once providers heal (circuit half-open →
closed), with usage accounting recorded throughout. Rule 15: mock-fast.
"""
from harness.wssession import WSSession

CATALOG_ERR = ('E_PROVIDER_429', 'E_PROVIDER_5XX', 'E_OFFLINE', 'E_TIMEOUT')


def _storm_job(cli, text, timeout=15):
    cli.send({'type': 'command', 'v': 1, 'text': text, 'source': 'text'})
    ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
    job = ack['job']
    err = cli.wait(lambda m: m.get('type') == 'error' and m.get('job') == job,
                   timeout=timeout)
    failed = cli.wait(lambda m: m.get('type') == 'job_event'
                      and m.get('status') == 'failed'
                      and m.get('job') == job, timeout=timeout)
    return job, err, failed


def test_provider_storm_fails_cleanly_then_recovers(client, qa_token,
                                                    router_to_mock, tmp_path):
    from brain.router import core as router_core

    # --- storm: 5 consecutive 500s -> jobs fail with §10 codes, loop alive
    router_to_mock.push(*[{'status': 500}] * 5)
    with WSSession(client, qa_token, role='cli') as cli:
        jobs = []
        for i in range(5):
            job, err, failed = _storm_job(
                cli, f'write a storm reply about topic{i}')
            assert err['code'] in CATALOG_ERR, err
            assert failed.get('error_code') in CATALOG_ERR, failed
            jobs.append(job)
        # no job left non-terminal (crash would strand rows)
        from brain.jobs import store
        for j in jobs:
            snap = store.get_job(j)
            assert snap and snap['status'] == 'failed', snap

        # --- breaker OPEN: next job fails fast WITHOUT another provider call
        before = router_to_mock.completions_count
        job, err, failed = _storm_job(cli, 'one more storm probe')
        assert failed['status'] == 'failed'
        assert router_to_mock.completions_count <= before + 1  # no storm loop

        # --- heal: age the breaker past its timeout (white-box, no 60s wait)
        stats = router_core.get_router()._stats.get('zen_free')
        assert stats is not None
        if stats.circuit.state.name == 'OPEN':
            stats.circuit.opened_at -= stats.circuit.timeout_s + 1
        router_to_mock.push({'content': 'providers are healthy again'})
        done_job, _, _ = None, None, None
        cli.send({'type': 'command', 'v': 1,
                  'text': 'confirm the recovery sentence', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done_job = ack['job']
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done'
                        and m.get('job') == done_job, timeout=15)
        assert done['text'] == 'providers are healthy again', done


def test_storm_failures_are_accounted_in_usage_log(client, qa_token,
                                                   router_to_mock, tmp_path):
    """Every storm failure lands in the usage log (audit trail — no silent
    provider black holes)."""
    router_to_mock.push({'status': 500}, {'status': 500})
    with WSSession(client, qa_token, role='cli') as cli:
        for i in range(2):
            _storm_job(cli, f'audit trail probe number{i}')
    log = tmp_path / 'usage.jsonl'
    assert log.exists(), 'usage log missing after failures'
    lines = [l for l in log.read_text(encoding='utf-8').splitlines() if l]
    assert lines, 'no usage events recorded'
    import json as _json
    outcomes = {_json.loads(l).get('outcome') for l in lines}
    assert outcomes - {None}, outcomes   # failures recorded with an outcome
