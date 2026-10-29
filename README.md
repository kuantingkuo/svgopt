# svgopt

Command-line SVG optimizer for GrADS-style scientific plots. It concatenates suitable consecutive same-color filled paths, runs SVGO at five decimal places with multipass enabled, and merges again after SVGO.

One input file produces one optimized output file; the original stays untouched.

## Requirements

- Python 3.10 or later (standard library only)
- Node.js and `svgo` 4.x, installed separately

Install SVGO:

```bash
npm install -g svgo@4.1.0
```

## Install from a Git checkout

```bash
git clone https://github.com/kuantingkuo/svgopt.git
cd svgopt
python -m pip install .
```

If the repository is private, clone it with an authenticated GitHub account, for example using `gh repo clone kuantingkuo/svgopt` after `gh auth login`.

### Linux (micromamba)

```bash
micromamba create -n svgtools -c conda-forge python=3.12 nodejs=24 pip -y
micromamba activate svgtools
npm install -g --prefix "$CONDA_PREFIX" svgo@4.1.0
python -m pip install .
svgopt --help
```

If you already have the `svgtools` environment and SVGO, only the `pip install .` step is needed.

### Windows PowerShell

Install Python and Node.js first, then:

```powershell
npm.cmd install -g svgo@4.1.0
py -m pip install --user .
svgopt --help
```

If Windows reports that the Python Scripts directory is not on PATH, add the exact directory reported by pip to your user PATH and restart PowerShell.

## Usage

```bash
svgopt figure.svg
svgopt figure1.svg figure2.svg
svgopt "*.svg"
svgopt -r figures/
svgopt figure.svg -o result.svg
svgopt -f figure.svg
svgopt --help
```

By default, `figure.svg` becomes `figure_opt.svg`. Existing output files are skipped unless `-f` / `--overwrite` is specified. Files already named `*_opt.svg` are skipped as inputs.

On Windows, the program automatically resolves the npm-provided `svgo.cmd` launcher.

## How it works

1. Read the original SVG and concatenate consecutive sibling `<path>` elements that have identical inline styles and transforms and are opaque, un-stroked solid fills.
2. Run `svgo --precision 5 --multipass`.
3. Repeat the conservative same-color concatenation on the SVGO output.
4. Write the final output atomically, leaving the original unchanged.

This is path concatenation, **not geometric union**. It does not close actual coordinate gaps, reconstruct contours, or change different-color borders. It also does not perform rasterization.

### Limitations

- Compound-path fill winding may cause visible changes if the source paths overlap with opposing winding directions.
- Only paths with supported attributes and explicit inline fill/stroke styles are eligible.
- SVG documents with embedded CSS, animations, an external stylesheet, or a DTD are not merged in the Python step.
- Referenced IDs are preserved; other IDs may be removed during concatenation.
- SVGO itself can change SVG rendering in edge cases, even with precision 5.
- **Always inspect scientific figures visually before publication**, especially thin contour boundaries and complex fills.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

No license has been specified. All rights reserved until the repository owner adds one.
