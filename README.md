# NGS Noct

英数字と基本記号を収録した、等幅・プロポーショナルの2書体です。

- 見本ページ: [site/index.html](site/index.html)
- フォント作成・GitHub Releases手順: [docs/FONT_BUILD.md](docs/FONT_BUILD.md)
- 収録文字: [docs/FONT_CHARACTERS.txt](docs/FONT_CHARACTERS.txt)
- draw.io原稿: [`source/`](source/)

## 構成

- `source/`: draw.io原稿
- `charsvg/`: 1字ずつに分割したSVG
- `tools/`: 字形抽出、フォント生成、Release梱包スクリプト
- `fonts/`: NGS Noct M/PのTTF・WOFF2
- `site/`: GitHub Pages用の見本・ダウンロードページ
- `.github/workflows/`: Pages公開とタグ付きReleaseの自動処理

Windowsではルートの`build_fonts.bat`で字形の再取得とサイト用WOFF2の同期ができます。