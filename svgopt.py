#!/usr/bin/env python3
"""Merge adjacent opaque same-color SVG paths and optimize using SVGO."""
from __future__ import annotations
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def style_properties(style: str) -> dict[str, str]:
    properties = {}
    for entry in style.split(";"):
        if ":" in entry:
            key, value = entry.split(":", 1)
            properties[key.strip().lower()] = value.strip().lower()
    return properties

def referenced_ids(root: ET.Element) -> set[str]:
    references: set[str] = set()
    for element in root.iter():
        for name, value in element.attrib.items():
            if local_name(name) == "href" and value.startswith("#"):
                references.add(value[1:])
            references.update(re.findall(r"url\(\s*[\"']?#([^\)\"']+)", value))
            if local_name(name) in {"aria-labelledby", "aria-describedby"}:
                references.update(value.split())
    return references

def eligible_key(element: ET.Element | None, protected_ids: set[str]) -> tuple[str, str | None] | None:
    if element is None or local_name(element.tag) != "path":
        return None
    if set(element.attrib) - {"id", "d", "style", "transform"}:
        return None
    if element.get("id") in protected_ids:
        return None
    data = element.get("d", "").lstrip()
    if not data or data[0] not in "Mm":
        return None
    style = element.get("style", "")
    props = style_properties(style)
    fill = props.get("fill", "")
    if not fill or fill in {"none", "transparent"} or "url(" in fill:
        return None
    if props.get("stroke") != "none":
        return None
    if props.get("fill-rule", "nonzero") != "nonzero":
        return None
    if props.get("fill-opacity", "1") not in {"1", "1.0", "1.00"}:
        return None
    if props.get("opacity", "1") not in {"1", "1.0", "1.00"}:
        return None
    if any(name in props for name in (
        "filter", "mask", "clip-path", "mix-blend-mode",
        "isolation", "paint-order", "stroke-opacity",
    )):
        return None
    return style, element.get("transform")

def independent_path_data(data: str) -> str:
    return "M0 0 " + data if data.lstrip().startswith("m") else data

def merge_file(source: Path, destination: Path) -> tuple[int, int]:
    with source.open("rb") as fh:
        prolog = fh.read(4096).lower()
    if b"<?xml-stylesheet" in prolog or b"<!doctype" in prolog:
        shutil.copyfile(source, destination)
        return 0, 0
    tree = ET.parse(source)
    root = tree.getroot()
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("The input is not an SVG document")
    unsafe_markup = {"style", "script", "animate", "animateTransform", "animateMotion", "set"}
    if any(local_name(e.tag) in unsafe_markup for e in root.iter()):
        shutil.copyfile(source, destination)
        return 0, 0
    protected_ids = referenced_ids(root)
    groups = 0
    removed = 0
    for parent in list(root.iter()):
        siblings = list(parent)
        current: list[ET.Element] = []
        current_key: tuple[str, str | None] | None = None
        def flush() -> None:
            nonlocal groups, removed
            if len(current) < 2:
                return
            first = current[0]
            first.set("d", first.get("d", "") + " " + " ".join(
                independent_path_data(elem.get("d", "")) for elem in current[1:]
            ))
            for elem in current[1:]:
                parent.remove(elem)
            groups += 1
            removed += len(current) - 1
        for elem in siblings + [None]:
            key = eligible_key(elem, protected_ids)
            if key is not None and key == current_key:
                current.append(elem)
            else:
                flush()
                current = [elem] if key is not None else []
                current_key = key
    tree.write(destination, encoding="utf-8", xml_declaration=False)
    return groups, removed

def expand_inputs(items: list[str], recursive: bool) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for item in items:
        matches = [Path(p) for p in glob.glob(item, recursive=True)] if glob.has_magic(item) else [Path(item)]
        for path in matches:
            if path.is_dir():
                candidates = sorted(path.rglob("*.svg") if recursive else path.glob("*.svg"))
            else:
                candidates = [path]
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.lower() != ".svg":
                    continue
                if candidate.name.lower().endswith("_opt.svg"):
                    continue
                identity = candidate.resolve()
                if identity not in seen:
                    paths.append(candidate)
                    seen.add(identity)
    return paths

def optimize_file(source: Path, target: Path, svgo_executable: str, precision: int,
                  overwrite: bool, verbose: bool) -> tuple[int, int, int, int] | None:
    if source.resolve() == target.resolve():
        raise ValueError("Input and output paths must differ")
    if target.exists() and not overwrite:
        print(f"SKIP: {target} already exists (use --overwrite)")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="svgopt-") as temp_dir:
        merged = Path(temp_dir) / "merged.svg"
        optimized = Path(temp_dir) / "optimized.svg"
        groups, removed = merge_file(source, merged)
        command = [
            svgo_executable, "--precision", str(precision), "--multipass",
            "-i", str(merged), "-o", str(optimized),
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            raise RuntimeError(
                f"SVGO failed (exit {process.returncode}): "
                f"{process.stderr.strip() or process.stdout.strip()}"
            )
        if verbose and process.stdout:
            print(process.stdout.rstrip())
        if not optimized.is_file():
            raise RuntimeError("SVGO returned success but did not create output")
        final_svg = Path(temp_dir) / "merged_after_svgo.svg"
        groups2, removed2 = merge_file(optimized, final_svg)
        groups += groups2
        removed += removed2
        before = source.stat().st_size
        after = final_svg.stat().st_size
        fd, temp_target = tempfile.mkstemp(prefix=".svgopt-", suffix=".svg", dir=target.parent)
        os.close(fd)
        try:
            shutil.copyfile(final_svg, temp_target)
            os.replace(temp_target, target)
        finally:
            if os.path.exists(temp_target):
                os.unlink(temp_target)
    return before, after, groups, removed

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge adjacent opaque same-color fills before/after SVGO (default precision 5).",
        epilog="Examples: svgopt figure.svg | svgopt *.svg | svgopt -r figures/",
    )
    parser.add_argument("inputs", nargs="+", help="SVG files, glob patterns, or directories")
    parser.add_argument("-r", "--recursive", action="store_true", help="Scan directories recursively")
    parser.add_argument("-o", "--output", type=Path, help="Output filename (single input only)")
    parser.add_argument("-p", "--precision", type=int, default=5, help="SVGO precision (default: 5)")
    parser.add_argument("-f", "--overwrite", action="store_true", help="Replace existing *_opt.svg files")
    parser.add_argument("--svgo", default="svgo", help="SVGO executable name or path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print SVGO output")
    args = parser.parse_args(argv)
    if args.precision < 0 or args.precision > 15:
        parser.error("--precision must be between 0 and 15")
    if os.name == "nt" and args.svgo == "svgo":
        args.svgo = shutil.which("svgo.cmd") or shutil.which("svgo.exe") or "svgo.cmd"
    if shutil.which(args.svgo) is None and not Path(args.svgo).is_file():
        print("ERROR: SVGO not found. Activate the environment containing SVGO, then run 'svgo --version'.", file=sys.stderr)
        return 2
    inputs = expand_inputs(args.inputs, args.recursive)
    if not inputs:
        print("ERROR: No input SVG files found (files ending in _opt.svg are skipped).", file=sys.stderr)
        return 2
    if args.output is not None and len(inputs) != 1:
        parser.error("--output requires exactly one input SVG")
    failures = 0
    for source in inputs:
        target = args.output if args.output is not None else source.with_name(f"{source.stem}_opt.svg")
        try:
            result = optimize_file(source, target, args.svgo, args.precision, args.overwrite, args.verbose)
            if result is None:
                continue
            before, after, groups, removed = result
            change = 100 * (before - after) / before if before else 0
            print(f"OK: {source} -> {target}")
            print(f"    {before:,} -> {after:,} bytes ({change:+.1f}% reduction); "
                  f"merged {groups} runs / removed {removed} paths")
        except (OSError, ValueError, ET.ParseError, RuntimeError) as exc:
            print(f"ERROR: {source}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
