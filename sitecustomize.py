import subprocess as _sp
_real_run = _sp.run
def _run(args, *a, **k):
    if isinstance(args, (list, tuple)) and args and str(args[0]).endswith("scutil") and "--get" in args:
        out = "Maya's MacBook Pro\n"
        return _sp.CompletedProcess(args, 0, stdout=out if (k.get("text") or k.get("universal_newlines")) else out.encode(), stderr="")
    return _real_run(args, *a, **k)
_sp.run = _run
