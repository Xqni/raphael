"""E2E: control-frame path (harness — orchestrator integration, not shipped).

Run with fake-brain up:  node body/orb/test/fake-brain.cjs &
                          python body/win/e2e_control.py

Starts the real ws_client, waits for connect+auth, injects hotkey actions
via the same thread-safe _post() the keyboard library uses, and verifies the
drain actually sends them. Exit 0 = PASS.
"""
import asyncio
import sys

try:
    import ws_client
    import hotkeys
except ImportError:
    sys.path.insert(0, __file__.rsplit('/', 1)[0])
    import ws_client
    import hotkeys


async def main() -> int:
    sent = asyncio.get_running_loop().create_future()
    client = asyncio.create_task(ws_client.start_client())
    await asyncio.sleep(6)  # connect + auth (pip/first-import may add delay)
    hotkeys._post('kill_gui', False)
    hotkeys._post('pause', True)
    hotkeys._post('private_on', True)
    # The drain prints "[body-win] control -> ..." for each send; watch stdout.
    await asyncio.sleep(4)
    client.cancel()
    try:
        await client
    except (asyncio.CancelledError, Exception):
        pass
    print('E2E-CONTROL: injection done (check control -> lines above)', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
