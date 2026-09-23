#!/usr/bin/env python3
"""Trim an OpenAPI 3 spec to an operationId allowlist + transitive $ref closure."""
import json
import sys


def collect_refs(node, refs: set):
    if isinstance(node, dict):
        r = node.get("$ref")
        if isinstance(r, str) and r.startswith("#/"):
            refs.add(r)
        for v in node.values():
            collect_refs(v, refs)
    elif isinstance(node, list):
        for v in node:
            collect_refs(v, refs)


def resolve(spec, ref):
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def main(src, dst, op_ids):
    spec = json.load(open(src))
    wanted = set(op_ids)
    kept_paths = {}
    for path, item in spec.get("paths", {}).items():
        kept_ops = {}
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") in wanted:
                kept_ops[method] = op
        if kept_ops:
            # keep path-level parameters etc. alongside the kept operations
            extras = {k: v for k, v in item.items() if not isinstance(v, dict) or "operationId" not in v}
            extras = {k: v for k, v in extras.items() if k in ("parameters", "servers")}
            kept_paths[path] = {**extras, **kept_ops}
    found = {op.get("operationId") for item in kept_paths.values() for op in item.values() if isinstance(op, dict)}
    missing = wanted - found
    if missing:
        sys.exit(f"operationIds not found in spec: {sorted(missing)}")

    # Transitive $ref closure over the kept operations.
    refs, frontier = set(), set()
    collect_refs(kept_paths, frontier)
    while frontier:
        refs |= frontier
        nxt = set()
        for r in frontier:
            try:
                collect_refs(resolve(spec, r), nxt)
            except KeyError:
                sys.exit(f"unresolvable $ref: {r}")
        frontier = nxt - refs

    # Rebuild components containing only referenced members (+ all securitySchemes).
    components = {}
    for r in sorted(refs):
        parts = r[2:].split("/")
        if parts[0] != "components" or len(parts) < 3:
            continue
        section, name = parts[1], "/".join(parts[2:]).replace("~1", "/").replace("~0", "~")
        components.setdefault(section, {})[name] = spec["components"][section][name]
    if "securitySchemes" in spec.get("components", {}):
        components["securitySchemes"] = spec["components"]["securitySchemes"]

    out = {
        "openapi": spec["openapi"],
        "info": {**spec["info"], "title": spec["info"].get("title", "") + " (trimmed for tests)"},
        "servers": spec.get("servers", []),
        "paths": kept_paths,
        "components": components,
    }
    if "security" in spec:
        out["security"] = spec["security"]
    json.dump(out, open(dst, "w"), separators=(",", ":"))
    import os
    print(f"{os.path.getsize(src) / 1e6:.1f}MB -> {os.path.getsize(dst) / 1e3:.0f}KB, "
          f"{len(kept_paths)} paths, {sum(len(v) for v in components.values())} components")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3].split(","))
