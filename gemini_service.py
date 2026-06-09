"""Gemini API ラッパー。

google-genai SDK を使用。APIキーは環境変数 GEMINI_API_KEY から読み込む。
本サービスは 3 つの AI 操作を提供する。

  1. propose_menu      … エッセンスを踏まえたメニュー提案
  2. summarize_log     … 提案＋フィードバックの客観要約（インジェスト ステップA）
  3. update_essences   … 既存エッセンス＋新サマリー → 最新エッセンス（ステップB）
"""

import json
import os

from google import genai
from google.genai import types

MODEL = "gemini-3.1-flash-lite"

# エッセンスとして扱うカテゴリの定義（key と日本語ラベル）。
# presentation_preference は「味」ではなく提案の“伝え方/出力形式”の好み
# （文量・前置きの有無・結論先行かどうか等）を保持する。
ESSENCE_KEYS: dict[str, str] = {
    "flavor_preference": "味の好み",
    "disliked_ingredients": "苦手な食材・NG",
    "favorite_menus": "お気に入りメニュー",
    "presentation_preference": "提案の伝え方・形式",
}


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("環境変数 GEMINI_API_KEY が設定されていません。")
    return genai.Client(api_key=api_key)


def _essences_to_text(essences: dict[str, str]) -> str:
    """エッセンス辞書をプロンプト埋め込み用のテキストへ整形する。"""
    if not essences or not any(v.strip() for v in essences.values()):
        return "（まだ学習データはありません。一般的な好みを想定してください。）"
    blocks = []
    for key, label in ESSENCE_KEYS.items():
        value = essences.get(key, "").strip() or "（情報なし）"
        blocks.append(f"## {label} ({key})\n{value}")
    return "\n\n".join(blocks)


def propose_menu(context: str, essences: dict[str, str]) -> str:
    """エッセンスを踏まえて今日のメニューを提案する。"""
    system_prompt = (
        "あなたは家庭料理に詳しい献立アドバイザーです。"
        "今日の気分や条件に合った具体的な献立を 1 案、提案してください。"
        "献立は主菜・副菜・汁物などの構成を意識します。\n"
        "下記『我が家の好みのエッセンス』を最大限尊重してください。"
        "特に『提案の伝え方・形式』の好みは、出力スタイル（文量・前置きの"
        "有無・結論先行かどうか・箇条書きにするか等）として最優先で守って"
        "ください。指定がなければ簡潔にまとめます。\n\n"
        "# 我が家の好みのエッセンス\n"
        f"{_essences_to_text(essences)}"
    )
    client = _client()
    response = client.models.generate_content(
        model=MODEL,
        contents=f"今日の気分や条件:\n{context}",
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return (response.text or "").strip()


def summarize_log(proposed_menu: str, feedback: str) -> str:
    """インジェスト ステップA: 提案＋フィードバックを客観要約する。"""
    system_prompt = (
        "あなたはデータ整理の専門家です。"
        "1 回分の『AIの献立提案』と『ユーザーのフィードバック』を読み、"
        "何が好評で、何が課題だったかを客観的かつ簡潔に要約してください。"
        "推測を交えず、事実ベースで 2〜4 文にまとめてください。"
    )
    client = _client()
    response = client.models.generate_content(
        model=MODEL,
        contents=(
            f"# 提案された献立\n{proposed_menu}\n\n"
            f"# ユーザーのフィードバック\n{feedback}"
        ),
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return (response.text or "").strip()


def update_essences(
    current_essences: dict[str, str], new_summaries: list[str]
) -> dict[str, str]:
    """インジェスト ステップB: 既存エッセンスへ新事実を反映する。

    JSON で各 key の最新 value を返させ、辞書として取り込む。
    """
    keys_desc = "\n".join(
        f"- {key}: {label}" for key, label in ESSENCE_KEYS.items()
    )
    # JSON 雛形は ESSENCE_KEYS から生成し、カテゴリ追加時のズレを防ぐ。
    json_skeleton = "{" + ", ".join(f'"{k}": "..."' for k in ESSENCE_KEYS) + "}"
    system_prompt = (
        "あなたは『我が家の好み』を管理するナレッジ・キュレーターです。"
        "既存のエッセンスに、新しく得られたサマリー（新事実）を反映し、"
        "追記・改訂してください。矛盾があれば新しい事実を優先します。"
        "味に関する事実は flavor_preference / disliked_ingredients / "
        "favorite_menus へ、提案の文量・前置き・結論先行など“伝え方/形式”の"
        "事実は presentation_preference へ振り分けてください。"
        "各カテゴリの value はマークダウンの箇条書きで簡潔に保ってください。\n\n"
        "対象カテゴリ:\n"
        f"{keys_desc}\n\n"
        "出力は必ず次の形式の JSON のみとし、説明文は出力しないこと:\n"
        f"{json_skeleton}"
    )
    summaries_text = "\n".join(f"- {s}" for s in new_summaries)
    user_content = (
        "# 既存のエッセンス\n"
        f"{_essences_to_text(current_essences)}\n\n"
        "# 新しく得られたサマリー（新事実）\n"
        f"{summaries_text}"
    )

    client = _client()
    response = client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # JSON 取得に失敗した場合は既存値を維持する（破壊的更新を避ける）。
        return current_essences

    updated = dict(current_essences)
    for key in ESSENCE_KEYS:
        if key in parsed and isinstance(parsed[key], str):
            updated[key] = parsed[key].strip()
    return updated
