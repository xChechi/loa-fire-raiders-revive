"""Generate Java stub classes from the luaj call sites in the stock Lua."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CALL = re.compile(
    r"luaj\.callStaticMethod\(\s*(?P<cls>\"[^\"]+\"|self\.\w+)\s*,"
    r"\s*\"(?P<method>\w+)\"\s*,.*?,\s*\"(?P<sig>[^\"]+)\"\s*\)",
    re.DOTALL,
)
CLASS_VAR = re.compile(r"(\w+Class)\s*=\s*\"([^\"]+)\"")

_PRIM = {"V": "void", "Z": "boolean", "B": "byte", "C": "char", "S": "short",
         "I": "int", "J": "long", "F": "float", "D": "double"}
_ZERO = {"void": None, "boolean": "false", "byte": "(byte) 0", "char": "'\\0'",
         "short": "(short) 0", "int": "0", "long": "0L", "float": "0f",
         "double": "0d", "String": '""'}

DEVICE_ID = "LOA-HOME-0001"


def _parse_type(sig: str, i: int) -> tuple[str, int] | None:
    ch = sig[i]
    if ch in _PRIM:
        return _PRIM[ch], i + 1
    if ch == "L":
        end = sig.find(";", i)
        if end == -1:
            return None
        name = sig[i + 1 : end].replace("/", ".")
        return (name.rsplit(".", 1)[-1] if name.startswith("java.lang.") else name), end + 1
    return None


def java_decl(sig: str) -> tuple[list[str], str] | None:
    """JNI descriptor to (param java types, return java type), or None if malformed."""
    if not sig.startswith("("):
        return None
    close = sig.find(")")
    if close == -1:
        return None
    params: list[str] = []
    i = 1
    while i < close:
        parsed = _parse_type(sig, i)
        if parsed is None or parsed[1] > close:
            return None
        typ, i = parsed
        params.append(typ)
    ret = _parse_type(sig, close + 1)
    if ret is None or ret[1] != len(sig):
        return None
    return params, ret[0]


def scan(scripts_root: Path) -> dict[str, dict[str, list[str]]]:
    found: dict[str, dict[str, list[str]]] = {}
    for path in sorted(scripts_root.rglob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        local = {f"self.{k}": v for k, v in CLASS_VAR.findall(text)}
        for m in CALL.finditer(text):
            raw = m.group("cls")
            cls = raw.strip('"') if raw.startswith('"') else local.get(raw)
            if cls is None:
                continue
            sigs = found.setdefault(cls, {}).setdefault(m.group("method"), [])
            if m.group("sig") not in sigs:
                sigs.append(m.group("sig"))
    return found


def _body(cls_simple: str, method: str, params: list[str], ret: str) -> str:
    if method == "getDeviceId" and ret == "String":
        return f'        return "{DEVICE_ID}";'
    if method == "getPlatformConfigByName" and len(params) == 2:
        return "        return arg1;"
    if cls_simple == "Nslm" and method == "getConnectionStatus":
        return "        return 1;"
    zero = _ZERO.get(ret, "null")
    return "" if ret == "void" else f"        return {zero};"


def render(class_name: str, methods: dict[str, list[str]]) -> str:
    dotted = class_name.replace("/", ".")
    package, simple = dotted.rsplit(".", 1)
    out = [f"package {package};", "", "import android.util.Log;", "",
           "/** Generated stub: see client/gen_luaj_stubs.py. Do not edit by hand. */",
           f"public class {simple} {{", ""]
    for method in sorted(methods):
        for sig in methods[method]:
            decl = java_decl(sig)
            if decl is None:
                out.append(f"    // skipped {method}: malformed JNI signature "
                           f"{sig!r} in the stock Lua")
                out.append("")
                continue
            params, ret = decl
            args = ", ".join(f"{t} arg{i}" for i, t in enumerate(params))
            out.append(f"    public static {ret} {method}({args}) {{")
            out.append(f'        Log.i("LOAStub", "{simple}.{method}");')
            body = _body(simple, method, params, ret)
            if body:
                out.append(body)
            out.append("    }")
            out.append("")
    out.append("}")
    return "\n".join(out) + "\n"


DEST = Path("client/android/app/src/main/java")
WANTED = ("com/uuzu/nslm/JavaSuperSDKManager", "com/uuzu/nslm/JavaComSDKManager",
          "com/uuzu/nslm/Nslm")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", type=Path, default=Path(".stock/assets/scripts"))
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args(argv)

    found = scan(args.scripts)
    merged: dict[str, dict[str, list[str]]] = {}
    for raw_cls, methods in found.items():
        key = raw_cls.replace(".", "/")
        for method, sigs in methods.items():
            bucket = merged.setdefault(key, {}).setdefault(method, [])
            for sig in sigs:
                if sig not in bucket:
                    bucket.append(sig)

    for cls in WANTED:
        methods = merged.get(cls, {})
        path = args.dest / (cls + ".java")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(cls, methods), encoding="utf-8")
        print(f"{cls}: {len(methods)} methods -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
