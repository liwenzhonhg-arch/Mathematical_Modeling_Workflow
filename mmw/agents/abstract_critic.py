"""Abstract Critic Agent：摘要专项评审，按国赛标准打分并给出修改意见。"""

from __future__ import annotations

import json
import re

from mmw.agents.base import BaseAgent

# 剥离 LaTeX 命令名（保留大括号内的正文）和特殊符号，用于统计正文字数
_TEX_CMD_RE = re.compile(r"\\(begin|end)\{[^}]*\}|\\[a-zA-Z]+(\[[^\]]*\])?|[{}$%&]")


def _abstract_plain_text(abstract: str) -> str:
    """剥离 LaTeX 命令，返回纯文本正文。"""
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", abstract, re.S)
    return _TEX_CMD_RE.sub("", match.group(1) if match else abstract)


class AbstractCriticAgent(BaseAgent):
    """摘要评审 Agent。每次打分独立无记忆，防止前轮分数锚定。"""

    role = "abstract_critic"
    system_prompt_template = "system/abstract_critic.j2"

    def score(self, abstract: str, results_json: str) -> dict:
        """对摘要打分。返回 {"score": int, "dimensions": {...}, "issues": [...], "suggestions": [...]}。

        解析失败时返回 {"score": -1, ...}，调用方应降级处理而非阻塞。
        """
        # 打分必须无记忆：清空历史使系统提示重新注入
        self.chat_history.clear()
        self.current_token_count = 0

        plain = _abstract_plain_text(abstract)
        char_count = len(re.sub(r"\s", "", plain))
        has_keywords = "关键词" in abstract or "\\keywords" in abstract

        user_prompt = (
            f"## 待评审摘要（abstract.tex）\n\n{abstract}\n\n"
            f"## 求解程序真实产出的数值结果（results.json）\n\n{results_json}\n\n"
            f"## 程序统计的硬指标（以此为准，不要自己数）\n\n"
            f"- 正文字数（去除 LaTeX 命令与空白）：{char_count}\n"
            f"- 是否包含关键词行：{'是' if has_keywords else '否'}\n\n"
            f"请按系统提示的评分标准打分并输出 abstract_score.json。"
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)

        raw = artifacts.get("abstract_score.json", response)
        for candidate in self._json_candidates(raw):
            try:
                data = json.loads(candidate)
                if not isinstance(data, dict):
                    continue
                data["score"] = int(data.get("score", -1))
                data.setdefault("issues", [])
                data.setdefault("suggestions", [])
                data.setdefault("needs_upstream_data", False)
                return data
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return {"score": -1, "dimensions": {}, "issues": [], "suggestions": [],
                "needs_upstream_data": False, "raw_response": response[:1000]}

    @staticmethod
    def _json_candidates(raw: str) -> list[str]:
        """解析候选：原文 → 第一个 { 到最后一个 } 的切片。"""
        candidates = [raw]
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            candidates.append(raw[start:end + 1])
        return candidates
