import pytest
import asyncio
import body.win.hotkeys as hotkeys

@pytest.mark.asyncio
async def test_hotkey_queue_integration():
    """Real async test for hotkey queueing."""
    # Setup real loop
    loop = asyncio.get_running_loop()
    hotkeys.set_loop(loop)
    
    # Clear queue
    while not hotkeys._control_queue.empty():
        hotkeys._control_queue.get_nowait()
        
    # Trigger post
    hotkeys._post('pause', True)
    
    # Wait for the task to execute (since _post uses run_coroutine_threadsafe)
    await asyncio.sleep(0.1)
    
    frame = await hotkeys._control_queue.get()
    assert frame == {"type": "control", "v": 1, "action": "pause", "persist": True}
