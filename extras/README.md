# Extras

Optional files. Nothing in `ccsessions` reads or depends on them — the tool
writes plain Markdown and never sets a Quarto theme, so your own `_quarto.yml`
always wins. Use these only if you want the Nord look for rendered
transcripts.

## Nord themes for rendered transcripts

- `nord-dark.scss` / `nord-light.scss` — page themes (Bootstrap variables plus
  a few rules), one per color scheme
- `make-nord-light-theme.py` — writes `nord-light.theme`, a light syntax
  highlighting theme derived from the dark `nord.theme` that Quarto already
  ships. It is generated rather than committed so it tracks your Quarto
  version and nothing is redistributed.

### Use

Generate the syntax theme **in the directory holding the document**, then point
the front matter at all three:

```bash
cd path/to/transcripts
python3 /path/to/ccsessions/extras/make-nord-light-theme.py
```

```yaml
format:
  html:
    theme:
      light: /abs/path/to/extras/nord-light.scss
      dark: /abs/path/to/extras/nord-dark.scss
    highlight-style:
      light: nord-light.theme
      dark: nord
    toc: true
    toc-depth: 2
```

### Two Quarto quirks worth knowing

- `theme:` accepts an absolute path, but `highlight-style:` resolves custom
  `.theme` files **relative to the document only**. An absolute path there is
  silently ignored: no warning, no error, just uncolored code. Hence the
  "generate it next to the document" step above.
- A live document (`w` in ccsessions) is rewritten in full on every change, so
  front matter added to it by hand is lost on the next write. Put the block in
  a `_quarto.yml` in that directory instead. Note that this makes the directory
  a Quarto project, so prefer `quarto preview <file>` over a bare
  `quarto render`.

### Contrast

`h3` (the `You` / `Claude` turns) is `#88c0d0` — Nord's `nord8` — in dark mode.
The light theme uses a darkened `#4e909f` instead: `nord8` on a Snow Storm
background measures 1.74:1, below the 3:1 that large text needs.
