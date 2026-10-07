"""wiring bridge: sync tool entrypoint -> brain main loop (AGENT_RULES §5 —
mocks only; never start the real stack)."""
import asyncio

import pytest

from brain.tools.computer_use import wiring


def test_run_sync_from_worker_thread_uses_bound_loop():
    async def main():
        wiring.bind_loop(asyncio.get_running_loop())
        loop = asyncio.get_running_loop()
        assert wiring.resolve_main_loop() is loop

        async def coro():
            await asyncio.sleep(0)
            return "ok"

        # called the way loop.py calls tools: in a worker thread
        result = await asyncio.to_thread(wiring.run_sync, coro())
        assert result == "ok"

        with pytest.raises(RuntimeError, match="ON the main loop"):
            wiring.run_sync(coro())          # same-thread misuse must fail loudly
    asyncio.run(main())


def test_run_sync_without_a_loop_raises_and_closes():
    async def coro():
        return "never"
    asyncio.run(coro())                      # ensure no ambient loop state
    monkey_closed = []

    class _C:
        def close(self):
            monkey_closed.append(True)

    real = wiring.resolve_main_loop
    wiring.resolve_main_loop = lambda: None
    try:
        with pytest.raises(RuntimeError, match="main loop unavailable"):
            wiring.run_sync(_C())
    finally:
        wiring.resolve_main_loop = real
    assert monkey_closed                    # coroutine closed, no leak


def test_set_deps_lifecycle():
    d = wiring.set_deps(chat_timeout_s=12.5)
    try:
        assert wiring.get_deps() is d
        assert d.chat_timeout_s == 12.5
        filled = wiring.fill_defaults(d)
        assert filled.config is not None     # lazy defaults filled
        assert filled.gate is not None
    finally:
        wiring.reset_deps()
    assert wiring._deps is None
    with pytest.raises(TypeError):
        wiring.set_deps(bogus_key=1)         # loud on unknown seams
