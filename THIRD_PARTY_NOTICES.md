# Sources and third-party notices

## Danus

- Upstream: https://github.com/frenzymath/Danus
- Baseline commit: `6d92e8d415933ca2ef52fd1a4da73fdfcd418f1c`
- Included at `danus-setup/Danus/` as a source snapshot, without Git history, runtime data or local credentials.
- License: Apache License 2.0. The upstream [LICENSE](danus-setup/Danus/LICENSE) is preserved.

This distribution modifies Danus for a local-model deployment: role-gated CLI fallback, worker launch behavior, local provider setup, paper/web retrieval, IACR metadata indexing, source history, search preferences, and project-aware verification settings. It adds a separate portal and API wrapper. It is not an official Danus release.

See [NOTICE](NOTICE) and [UPSTREAM_CHANGES.md](UPSTREAM_CHANGES.md) for the modification record. Changed upstream files also carry a distribution notice.

Upstream author notices and documentation are retained. The vendored `OPERATOR.md` is an uninitialized template and contains no personal operator profile.

## Bundled browser assets

| Component | Location | License file |
|---|---|---|
| KaTeX 0.16.11 JavaScript and CSS | `webui/static/katex/` | [MIT notice](webui/static/licenses/katex-LICENSE) |
| KaTeX fonts | `webui/static/katex/fonts/` | [SIL OFL 1.1](webui/static/licenses/katex-fonts-OFL.txt), [copyright and reserved font names](webui/static/licenses/katex-fonts-NOTICE.txt) |
| marked | `webui/static/marked.min.js` | [MIT notices](webui/static/licenses/marked-LICENSE.md) |
| highlight.js | `webui/static/highlight/` | [BSD notice](webui/static/licenses/highlight-LICENSE) |

Original license files are included with these redistributed assets. Font copyright and reserved names are preserved from the bundled font metadata. See the [KaTeX maintainer's font-license clarification](https://github.com/KaTeX/KaTeX/issues/339#issuecomment-135518223) and the [official OFL text](https://openfontlicense.org/open-font-license-official-text/).

## Container images fetched separately

The repository references these upstream products rather than bundling their container images:

- [Open WebUI](https://github.com/open-webui/open-webui), pinned to `v0.11.4`; its own Open WebUI license and branding terms apply.
- [SearXNG](https://github.com/searxng/searxng), image pinned by digest in Compose; its own license applies.
- [go-llm-proxy](https://github.com/yatesdr/go-llm-proxy), image pinned by digest; upstream MIT license applies.
- [nginx](https://nginx.org/) and the Python Debian image, with their upstream licenses and bundled dependency notices.

The Dockerfile also installs Debian TeX Live packages. The runtime bootstrap downloads Node.js, Python packages and the Codex CLI. These retain their respective licenses; this package's Apache-2.0 license does not replace third-party terms.

## Data providers

- [arXiv API](https://info.arxiv.org/help/api/user-manual.html)
- [Crossref](https://www.crossref.org/documentation/retrieve-metadata/)
- [IACR metadata harvesting](https://eprint.iacr.org/rss/): metadata is offered under CC0; paper PDFs have individual licenses and access rules.
- [Wikipedia / MediaWiki API](https://www.mediawiki.org/wiki/API:Search)
- DuckDuckGo, Matlas and web-search sources retain their own service terms.

No paper corpus, model weights or user-uploaded documents are redistributed in this source package.
