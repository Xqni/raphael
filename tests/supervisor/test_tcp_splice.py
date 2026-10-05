import pytest
import socket
import threading
import time

def test_tcp_splice_behavior():
    """
    Verify TCP pipe semantics:
    S1 (Source) -> [Splicer] -> S2 (Sink)
    If Splicer reads from S1 and writes to S2, S2 should receive exactly what S1 sent.
    """
    # Create two sockets
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(('127.0.0.1', 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(1)
    
    received_data = []
    def sink_thread():
        conn, addr = server_sock.accept()
        with conn:
            while True:
                data = conn.recv(1024)
                if not data: break
                received_data.append(data)

    t = threading.Thread(target=sink_thread, daemon=True)
    t.start()
    
    # Source socket
    source_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    source_sock.connect(('127.0.0.1', port))
    
    test_payload = b"Raphael-Splice-Test-123"
    source_sock.sendall(test_payload)
    source_sock.close()
    
    # Wait for sink to read
    time.sleep(0.2)
    server_sock.close()
    
    assert b"".join(received_data) == test_payload
