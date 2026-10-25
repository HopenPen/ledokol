"""Проверка последовательного запуска обычных Python-ячеек с сохранением outputs без Jupyter-сервера."""
from __future__ import annotations

import ast
import base64
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")


def main():
    path = Path(sys.argv[1]).resolve()
    notebook = json.loads(path.read_text(encoding="utf-8"))
    os.chdir(path.parent)
    import matplotlib.pyplot as plt

    outputs = []

    def display(value):
        if value is None:
            return
        data = {"text/plain": [repr(value)]}
        if callable(getattr(value, "_repr_html_", None)):
            rendered = value._repr_html_()
            if rendered:
                data["text/html"] = [rendered]
        outputs.append({"output_type": "display_data", "data": data, "metadata": {}})

    def show(*args, **kwargs):
        for number in plt.get_fignums():
            stream = io.BytesIO()
            plt.figure(number).savefig(stream, format="png", dpi=120, bbox_inches="tight")
            outputs.append({"output_type": "display_data", "metadata": {},
                            "data": {"image/png": base64.b64encode(stream.getvalue()).decode("ascii")}})
        plt.close("all")

    plt.show = show
    namespace = {"__name__": "__main__", "__file__": str(path), "display": display}
    count = 0
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        count += 1
        outputs = []
        stdout, stderr = io.StringIO(), io.StringIO()
        started = time.perf_counter()
        print(f"Ячейка {index + 1}: запуск", flush=True)
        failure = None
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                tree = ast.parse("".join(cell["source"]), filename=f"{path.name}:cell{index + 1}")
                last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
                exec(compile(tree, str(path), "exec"), namespace)
                if last:
                    value = eval(compile(ast.Expression(last.value), str(path), "eval"), namespace)
                    display(value)
            except Exception as exc:
                failure = exc
                outputs.append({"output_type": "error", "ename": type(exc).__name__, "evalue": str(exc),
                                "traceback": traceback.format_exc().splitlines()})
        streams = [{"output_type": "stream", "name": name, "text": text.splitlines(keepends=True)}
                   for name, text in (("stdout", stdout.getvalue()), ("stderr", stderr.getvalue())) if text]
        cell["outputs"], cell["execution_count"] = streams + outputs, count
        path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Ячейка {index + 1}: {time.perf_counter() - started:.1f} с", flush=True)
        if failure:
            raise failure
    print(f"Готово: {count} ячеек выполнены, outputs сохранены в {path.name}", flush=True)


if __name__ == "__main__":
    main()
