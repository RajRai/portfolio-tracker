import subprocess
import signal
import sys
import time

processes = []

def shutdown(signum, frame):
    print("\n🛑 Received shutdown signal, terminating child processes...")
    for p in processes:
        if p.poll() is None:
            p.terminate()
    # Give them a second to exit gracefully
    time.sleep(1)
    for p in processes:
        if p.poll() is None:
            p.kill()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    cmds = [
        ["python", "watch.py"],
        ["python", "server.py"]
    ]

    for cmd in cmds:
        print(f"▶️ Starting {' '.join(cmd)}")
        p = subprocess.Popen(cmd)
        processes.append(p)

    # Wait for any process to exit
    while True:
        for p in processes:
            if p.poll() is not None:
                print(f"❌ Process {' '.join(cmds[processes.index(p)])} exited with code {p.returncode}")
                shutdown(None, None)
        time.sleep(1)

if __name__ == "__main__":
    main()