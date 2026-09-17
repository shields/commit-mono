# Commit Mono

Commit Mono is an anonymous and neutral programming typeface focused on creating a better reading experience.

[**Customize download, explore the font**](https://commitmono.com/)

[**Download latest default version**](https://github.com/eigilnikolajsen/commit-mono/releases/latest/)

<br>

If you wish to support this project directly [**buy me a coffee**](https://www.buymeacoffee.com/eigilnikolajsen).

![Commit Mono concept image](/src/img/commitmono.png)

## Development

The fonts in `src/fonts/` were exported from FontLab and are the source of truth; the
repository has no editable font sources. The [developer documentation](docs/README.md)
describes the repository layout and the font internals, and `tools/` provides `cmfont`, a
command that decompiles the binaries into UFO sources, rebuilds them with fontmake, verifies
the rebuild against the originals, and renders proof sheets. See
[docs/building.md](docs/building.md).

## Licenses

-   **Font files** (`src/fonts/`, font assets and fonts generated from the website): Licensed under the [SIL Open Font License](LICENSE-FONT)
-   **Website code** (HTML, CSS, JavaScript, and other source code): Licensed under the [MIT License](LICENSE)
