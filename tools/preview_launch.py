import os, socket, subprocess, sys, time

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(TOOL, "preview", "server.py")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def listener_pid():
    out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    for line in out.splitlines():
        if ":8765" in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def command_line(pid):
    script = "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid
    out = subprocess.check_output(["powershell", "-NoProfile", "-Command", script], text=True, errors="replace")
    return out.strip()


def ensure_built():
    projects = [
        (os.path.join(TOOL, "tools", "RigDump", "RigDump.csproj"), os.path.join(TOOL, "tools", "RigDump", "bin", "Release", "net10.0", "RigDump.exe")),
        (os.path.join(TOOL, "tools", "Assemble", "Assemble.csproj"), os.path.join(TOOL, "tools", "Assemble", "bin", "Release", "net10.0", "Assemble.exe")),
    ]
    for project, exe in projects:
        if os.path.isfile(exe):
            continue
        print("正在编译 " + os.path.basename(project))
        subprocess.check_call(["dotnet", "build", project, "-c", "Release"])


def main():
    pid = listener_pid()
    if pid:
        command = command_line(pid)
        if os.path.normcase(SERVER) in os.path.normcase(command):
            os.startfile("http://127.0.0.1:8765/index.html")
            print("预览已在运行。")
            return 0
        print("8765 端口已被其他程序占用。请先关掉原来的预览，再运行 Preview.bat。")
        print(command)
        return 1
    ensure_built()
    subprocess.Popen([sys.executable, SERVER], cwd=TOOL, creationflags=subprocess.CREATE_NEW_CONSOLE)
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", 8765), 0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        print("预览没有启动。")
        return 1
    os.startfile("http://127.0.0.1:8765/index.html")
    print("预览已打开。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
