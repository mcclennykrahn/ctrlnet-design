"""从 scripts/run_demo.py 的 `# %%` 单元标记生成 notebooks/demo.ipynb。

保持脚本与 notebook 同源，避免两份演示代码漂移。
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_demo.py"
NOTEBOOK = ROOT / "notebooks" / "demo.ipynb"


def _strip_markdown(line: str) -> str:
    if line.startswith("# "):
        return line[2:]
    if line.startswith("#"):
        return line[1:]
    return line


def parse_cells(source: str) -> list:
    cells: list = []
    mode: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal mode, buffer
        if mode is None:
            return
        text = "\n".join(buffer).strip("\n")
        if mode == "markdown":
            content = "\n".join(_strip_markdown(line) for line in buffer).strip()
            if content:
                cells.append(nbf.v4.new_markdown_cell(content))
        else:
            if text:
                cells.append(nbf.v4.new_code_cell(text))
        buffer = []

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("# %% [markdown]"):
            flush()
            mode = "markdown"
        elif stripped.startswith("# %%"):
            flush()
            mode = "code"
        else:
            buffer.append(line)
    flush()
    return cells


def main() -> None:
    cells = parse_cells(SCRIPT.read_text(encoding="utf-8"))
    notebook = nbf.v4.new_notebook(cells=cells)
    notebook.metadata["kernelspec"] = {
        "display_name": "ctrlnet (.venv)",
        "language": "python",
        "name": "ctrlnet-venv",
    }
    notebook.metadata["language_info"] = {"name": "python"}
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(notebook, str(NOTEBOOK))
    print(f"wrote {NOTEBOOK} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
