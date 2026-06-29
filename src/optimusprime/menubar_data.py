"""Data loading layer for OptimusPrime menu bar / system tray apps.

No UI dependencies — importable anywhere, fully testable.
Reads from .optimusprime/ every call to load(). Silent on all errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MenuBarData:
    """Loads and holds OptimusPrime state from .optimusprime/."""

    def __init__(self, op_dir: Optional[Path] = None) -> None:
        self.op_dir = op_dir
        self.data: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def find_op_dir(self) -> bool:
        """Walk from cwd upward looking for .optimusprime/. Returns True if found."""
        try:
            current = Path.cwd().resolve()
            for _ in range(10):
                candidate = current / ".optimusprime"
                if candidate.is_dir():
                    self.op_dir = candidate
                    return True
                parent = current.parent
                if parent == current:
                    break
                current = parent
            home_op = Path.home() / ".optimusprime"
            if home_op.is_dir():
                self.op_dir = home_op
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Reload all data from .optimusprime/. Silent on any error."""
        if self.op_dir is None or not self.op_dir.is_dir():
            self.find_op_dir()
        if self.op_dir is None or not self.op_dir.is_dir():
            self.data = {}
            return

        data: Dict[str, Any] = {}

        # contract.json
        try:
            c = _read_json(self.op_dir / "contract.json")
            if c:
                data["goal"] = str(c.get("goal", ""))[:35]
                data["budget"] = c.get("complexity_budget", "")
        except Exception:
            pass

        # cost-log.json
        try:
            cl = _read_json(self.op_dir / "cost-log.json")
            sessions = cl.get("sessions", [])
            if sessions:
                s = sessions[-1]
                t = s.get("token_estimate", s.get("estimated_input_tokens", 0))
                data["tokens"] = t
                data["cost"] = s.get("estimated_cost_usd", s.get("cost_estimate", 0.0))
        except Exception:
            pass

        # decisions.md
        try:
            dec_path = self.op_dir / "decisions.md"
            if dec_path.is_file():
                lines = [
                    l for l in dec_path.read_text(encoding="utf-8").splitlines()
                    if "DECIDED" in l or "DECISION" in l
                ]
                data["decision_count"] = len(lines)
                data["last_decisions"] = lines[-3:]
        except Exception:
            pass

        # loop-state.json
        try:
            lp = _read_json(self.op_dir / "loop-state.json")
            failures = lp.get("consecutive_failures", [])
            data["loop_streak"] = len(failures) if isinstance(failures, list) else int(failures)
        except Exception:
            pass

        # skills.json
        try:
            sk = _read_json(self.op_dir / "skills.json")
            installed = sk.get("installed", {})
            data["skills"] = {
                k: (v.get("mode", "manual") if isinstance(v, dict) else "manual")
                for k, v in installed.items()
            }
        except Exception:
            pass

        # compression-log.json
        try:
            cmp_path = self.op_dir / "compression-log.json"
            if cmp_path.is_file():
                raw = json.loads(cmp_path.read_text(encoding="utf-8"))
                entries = raw if isinstance(raw, list) else raw.get("entries", [])
                if entries:
                    ratios = [e.get("ratio", 0) for e in entries if e.get("ratio")]
                    if ratios:
                        data["compression"] = sum(ratios) / len(ratios)
        except Exception:
            pass

        # self-model.json
        try:
            sm = _read_json(self.op_dir / "self-model.json")
            conf = sm.get("confidence_map", {})
            low: List[Tuple[str, float]] = []
            for k, v in conf.items():
                if isinstance(v, dict):
                    c_val = float(v.get("confidence", 1.0))
                elif isinstance(v, (int, float)):
                    c_val = float(v)
                else:
                    continue
                if c_val < 0.5:
                    low.append((k, c_val))
            if low:
                data["risks"] = low
        except Exception:
            pass

        self.data = data

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def title(self) -> str:
        """Build menu bar title string. '⚡OP' minimum."""
        tokens = self.data.get("tokens", 0)
        cost = self.data.get("cost", 0.0)
        if tokens and tokens > 0:
            tok_str = f"{tokens // 1000}k" if tokens >= 1000 else str(tokens)
            return f"⚡OP tok:{tok_str} ${cost:.2f}"
        return "⚡OP"


# ------------------------------------------------------------------
# Module-level helper
# ------------------------------------------------------------------

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}
