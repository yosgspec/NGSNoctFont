# フォントの作成方法

draw.io原稿は `source/`、生成ツールは `tools/`、分割済み字形は `charsvg/` にあります。`source/`直下のSVGを1つ自動検出するため、原稿ファイル名は任意です。Windowsでは [../build_fonts.bat](../build_fonts.bat) をダブルクリックすると、字形抽出・フォント生成・サイト用WOFF2の同期を一括実行できます。必要なライブラリがない場合は自動でインストールします。

バッチ実行時のフォント生成先はGit管理外の `build/fonts` です。既存のTTFを開いていても上書きエラーにならないよう、出力先を分けています。作成後、見本ページ用のWOFF2を `site/fonts` にコピーします。

見本ページは [../site/index.html](../site/index.html) です。Pages workflowは `main` または `master` への更新、もしくは手動実行で公開します。GitHubリポジトリのSettingsでPagesの公開元をGitHub Actionsに設定してください。

公開ページは `https://<所有者>.github.io/<リポジトリ名>/` です。workflowがGitHubの実リポジトリ名をダウンロード先リンクへ埋め込むため、リポジトリ名の変更後もソースに固定URLを残しません。

```powershell
python -m pip install -r tools/requirements-fonts.txt
python tools/split_glyphs.py --output-dir build/charsvg --overwrite
python tools/build_fonts.py --glyph-dir build/charsvg --output-dir fonts
```

コマンドから実行した場合は、次の4ファイルが `fonts` に生成されます。

- `fonts/NGSNoctM.ttf` と `fonts/NGSNoctM.woff2` (フォント名: `NGS Noct M`)
- `fonts/NGSNoctP.ttf` と `fonts/NGSNoctP.woff2` (フォント名: `NGS Noct P`)

各フォントには、空白、数字、大文字、小文字、および指定した45記号が入ります。TTFはパソコンへのインストール用、WOFF2はWebページでの使用に適した形式です。片方だけ作る場合は、`build_fonts.py` に `--variant lc1` または `--variant lc2` を指定してください。

LC1は空白を含むすべての文字の送り幅を500 unitsに統一した等幅です。LC2は字形の幅に合わせて送り幅を変えるプロポーショナルです。線画はフォントで扱える塗りつぶし輪郭に変換してから収録します。

記号45字のうち37字はグループ、8字は単独図形です。さらに、1本だけグループ外にある線は接している記号の一部として自動で取り込みます。

収録文字と記号の図面上の並びは [FONT_CHARACTERS.md](FONT_CHARACTERS.md) を参照してください。

## GitHub Releases

`../.github/workflows/release-fonts.yml` は `v1.2.3` のようなタグをpushすると実行されます。図面から字形を取り出し、4種類のフォント・108文字・等幅/プロポーショナル設定を検証してから、次のファイルをGitHub Releaseへ添付します。

- `NGS-Noct-v1.2.3.zip` (4フォントと収録文字一覧)
- `NGS-Noct.zip` (最新版への固定名リンク)
- `NGSNoctM.ttf` / `NGSNoctM.woff2` / `NGSNoctP.ttf` / `NGSNoctP.woff2`
- `SHA256SUMS.txt`

リリース梱包処理は `tools/build_release.py` です。

公開時は、作成したバージョンに合わせてタグを付けてpushします。

```powershell
git tag v1.0.0
git push origin v1.0.0
```

この作業環境のNGSCSFontにはGit remoteが設定されていないため、実際にReleaseを公開する前にGitHubリポジトリのremoteを設定してください。また、リポジトリにライセンスファイルがないため、公開前に配布条件を決めてライセンスを追加してください。