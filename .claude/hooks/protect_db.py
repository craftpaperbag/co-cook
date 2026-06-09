#!/usr/bin/env python3
"""PreToolUse(Bash) ガード: co_cook.db への破壊的操作をブロックする。

stdin に渡される hook 入力 JSON から実行予定の bash コマンドを取り出し、
co_cook.db を「削除 / 上書き / truncate / DROP / DELETE」しようとしている
場合のみ permissionDecision=deny を返す。バックアップ用の
`cp co_cook.db backup.db` のような読み取り側参照はブロックしない。

auto / acceptEdits / bypassPermissions など、権限プロンプトが出ないモードでも
ハーネスがこのフックを実行するため、確実に停止できる。
"""

import json
import re
import sys

DB = r"co_cook\.db"

# 破壊的とみなすパターン（いずれか1つでもマッチすればブロック）。
DESTRUCTIVE = [
    # rm / unlink / shred / truncate が co_cook.db を対象にしている
    rf"\b(rm|unlink|shred|truncate)\b[^|;&]*{DB}",
    # ファイルへの上書きリダイレクト ( > co_cook.db / >| co_cook.db )。
    # 追記 (>>) は別途下で除外する。
    rf"(?<!>)>\|?\s*['\"./]*{DB}",
    # cp / mv の「コピー先」が co_cook.db（＝末尾が co_cook.db）。
    rf"\b(cp|mv|dd|install)\b[^|;&]*{DB}\s*['\"]?$",
    # sqlite などでの DROP TABLE / DELETE FROM
    r"\bdrop\s+table\b",
    r"\bdelete\s+from\b",
    # 空にする系 (: > co_cook.db / cat /dev/null > ...) は上の > で捕捉。
]

DENY_REASON = (
    "co_cook.db への破壊的操作（削除 / 上書き / truncate / DROP / DELETE）を"
    "検知したためブロックしました。意図的に実行する場合は、このフックを一時的に"
    "無効化するか、ターミナルで `! <command>` を使って手動実行してください。"
)


def is_destructive(command: str) -> bool:
    if not re.search(DB, command):
        return False
    # 追記リダイレクト (>>) はデータを消さないので許可する。
    for pattern in DESTRUCTIVE:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # 解析不能なら何もしない（通常フローへ）
    command = (payload.get("tool_input") or {}).get("command", "")
    if isinstance(command, str) and is_destructive(command):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": DENY_REASON,
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
