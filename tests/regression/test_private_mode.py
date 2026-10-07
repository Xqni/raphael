"""Regression: Private Mode = ZERO cloud calls (PROTOCOL §7/§11, WAVES
cloud_temp rules). With the router pointed at a counting mock server:

- private on + a non-fastpath request → no HTTP request reaches ANY provider
  (including model discovery); the job completes locally with
  PRIVATE_NOTICE — never a model reply, never a provider error frame;
- private on → the fastpath (deterministic intents, incl. Body acts) still
  works — local code paths stay local;
- private is an orb `mode` overlay, not an orb state (INTERFACES §e).
"""
from harness.mock_body import MockBody
from harness.wssession import WSSession


def test_private_makes_zero_provider_calls_and_job_done(client, qa_token,
                                                        router_to_mock):
    """Private on + non-fastpath request → NO HTTP reaches any provider
    (incl. discovery); the job completes with the local PRIVATE_NOTICE
    (merged brain-core: private = graceful local completion, not a failure)."""
    from brain.loop import PRIVATE_NOTICE
    assert router_to_mock.count == 0           # sanity: counting mock is live
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'control', 'v': 1, 'action': 'private_on',
                  'persist': True})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)

        cli.send({'type': 'command', 'v': 1,
                  'text': 'explain the tides like a poet', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done'
                        and m.get('job') == job, timeout=10)
        assert done['text'] == PRIVATE_NOTICE, done
        # no provider error frame may appear for a private-mode job
        errs = [f for f in cli.frames if f.get('type') == 'error'
                and f.get('job') == job]
        assert errs == [], errs

    # THE invariant: not a single request — no discovery, no completion
    assert router_to_mock.count == 0, [
        r['path'] for r in router_to_mock.requests]


def test_private_mode_still_runs_local_fastpath(client, qa_token,
                                                router_to_mock):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'control', 'v': 1, 'action': 'private_on'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)

        cli.send({'type': 'command', 'v': 1, 'text': 'echo local only',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done', timeout=8)
        assert done['text'] == 'Echo: local only'
    assert router_to_mock.count == 0


def test_private_mode_body_act_is_not_a_cloud_call(client, qa_token,
                                                   router_to_mock):
    """PROTOCOL §7: Private Mode blocks MODEL calls; fastpath Body acts
    (screenshot capture stays local to the machine) remain available."""
    with MockBody(client, qa_token) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'control', 'v': 1, 'action': 'private_on'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        cli.send({'type': 'command', 'v': 1, 'text': 'take a screenshot',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        body.next_act_req(timeout=10)
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done', timeout=8)
        assert done['job'].startswith('j_')
    assert router_to_mock.count == 0


def test_private_is_mode_overlay_not_state(client, qa_token):
    """INTERFACES §e: private renders as `mode`, base `state` stays a valid
    semantic state (private_overlay is a legacy client value — the server
    emits mode=private on top of a normal state, never as the state)."""
    from brain.orbstate import VALID_STATES
    with WSSession(client, qa_token, role='ui') as ui:
        ui.drain(quiet=0.3, cap=1.0)
        ui.send({'type': 'control', 'v': 1, 'action': 'private_on'})
        ui.wait(lambda m: m.get('type') == 'ack', timeout=5)
        frame = ui.wait(lambda m: m.get('type') == 'orb_state'
                        and m.get('mode') == 'private', timeout=5)
        assert frame['mode'] == 'private'
        assert frame['state'] in VALID_STATES, frame
        assert frame['state'] != 'private_overlay', \
            'private must be a mode overlay, not an orb state (§e)'
        # and off again → mode back to normal
        ui.send({'type': 'control', 'v': 1, 'action': 'private_off'})
        ui.wait(lambda m: m.get('type') == 'ack', timeout=5)
        frame = ui.wait(lambda m: m.get('type') == 'orb_state'
                        and m.get('mode') == 'normal', timeout=5)
        assert frame['mode'] == 'normal'
