import os, subprocess, sys

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(TOOL, "tools", "SekiroExtract", "SekiroExtract", "SekiroExtract.csproj")
EXE = os.path.join(TOOL, "tools", "SekiroExtract", "SekiroExtract", "bin", "Release", "net10.0", "SekiroExtract.exe")
KEYS = os.path.join(TOOL, "tools", "keys", "Sekiro_PC")
CONFIG = os.path.join(TOOL, "config.json")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    if not os.path.isfile(CONFIG):
        print("缺少 config.json。请先运行 SetGameDir.bat。")
        return 1
    if not os.path.isfile(EXE):
        print("正在编译抽取程序。")
        subprocess.check_call(["dotnet", "build", PROJECT, "-c", "Release"])
    return subprocess.call([EXE, CONFIG, KEYS])


if __name__ == "__main__":
    raise SystemExit(main())
