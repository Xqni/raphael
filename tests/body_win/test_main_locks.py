import pytest
import os
import pathlib
import body.win.main as main

def test_lock_reclaim_stale_pid(tmp_path, monkeypatch):
    """Verify that a lock with a dead PID is reclaimed."""
    # Setup: monkeypatch LOCK_PATH to a temp file
    lock_file = tmp_path / "raphael_body.lock"
    monkeypatch.setattr(main, "LOCK_PATH", lock_file)
    
    # Write a non-existent PID (using a very high number)
    # On Linux/Windows, 999999 is usually safe for 'not running'
    lock_file.write_text("999999")
    
    # Should reclaim the lock and return True
    assert main.obtain_lock() is True
    assert lock_file.read_text() == str(os.getpid())

def test_lock_blocks_live_pid(tmp_path, monkeypatch):
    """Verify that a lock with a live PID blocks access."""
    lock_file = tmp_path / "raphael_body.lock"
    monkeypatch.setattr(main, "LOCK_PATH", lock_file)
    
    # Write current PID
    lock_file.write_text(str(os.getpid()))
    
    # Since it's the SAME process, _pid_alive will return True
    # obtain_lock should return False
    assert main.obtain_lock() is False

def test_release_lock(tmp_path, monkeypatch):
    """Verify lock is deleted on release."""
    lock_file = tmp_path / "raphael_body.lock"
    monkeypatch.setattr(main, "LOCK_PATH", lock_file)
    
    lock_file.write_text("123")
    main.release_lock()
    assert not lock_file.exists()
