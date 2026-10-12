import json, os, sys

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(TOOL, "config.json")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ask(label, current):
    print(label)
    if current:
        print("当前: " + current)
    entered = input("直接回车保持当前值: ").strip().strip('"')
    return entered or current


def main():
    data = {"gameDir": "", "resourceDir": ""}
    if os.path.isfile(PATH):
        with open(PATH, encoding="utf-8") as handle:
            data.update(json.load(handle))
    print("设置游戏目录和资源目录。")
    game = ask("游戏目录（里面要有 sekiro.exe 和 Data3.bhd）", data.get("gameDir") or "")
    resource = ask("资源目录（存放 raw、unpacked、preview，不要选本工具目录）", data.get("resourceDir") or "")
    game = os.path.abspath(game) if game else ""
    resource = os.path.abspath(resource) if resource else ""
    if not game or not os.path.isfile(os.path.join(game, "Data3.bhd")):
        print("游戏目录里找不到 Data3.bhd。")
        return 1
    tool = os.path.normcase(os.path.abspath(TOOL))
    if not resource or os.path.normcase(resource) == tool or os.path.normcase(resource).startswith(tool + os.sep):
        print("资源目录不能放在工具目录里面。")
        return 1
    os.makedirs(resource, exist_ok=True)
    data["gameDir"] = game
    data["resourceDir"] = resource
    with open(PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("已保存 " + PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
