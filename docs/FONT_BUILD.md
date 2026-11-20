# フォントの作成方法

生成ツールは `tools/`、正本となる個別字形SVGは `src/charsvg/`、参考用のdraw.io原稿は `src/` にあります。Windowsでは [../build_fonts.bat](../build_fonts.bat) を実行すると、`src/charsvg/` の字形からフォント生成およびサイト用WOFF2の同期を一括実行できます。必要なライブラリがない場合は自動でインストールします。

> [!NOTE]
> 現在の運用では `src/charsvg/` 配下の字形SVGファイルを直接更新・管理します。原本（draw.io）からの抽出処理（`tools/split_glyphs.py`）は検証用途以外では実行しません。

バッチ実行時のフォント生成先はGit管理外の `build/fonts` です。既存のTTFを開いていても上書きエラーにならないよう、出力先を分けています。作成後、見本ページ用のWOFF2を `site/fonts` にコピーします。

見本ページは [../site/index.html](../site/index.html) です。Pages workflowは `main` または `master` への更新、もしくは手動実行で公開します。GitHubリポジトリのSettingsでPagesの公開元をGitHub Actionsに設定してください。

公開ページは `https://<所有者>.github.io/<リポジトリ名>/` です。workflowがGitHubの実リポジトリ名をダウンロード先リンクへ埋め込むため、リポジトリ名の変更後もソースに固定URLを残しません。

```powershell
python -m pip install -r tools/requirements-fonts.txt
python tools/optimize_glyph_paths.py --glyph-dir src/charsvg
python tools/build_fonts.py --glyph-dir src/charsvg --output-dir fonts
```

コマンドから実行した場合は、M/P/MF/PF、Regular/Boldの組み合わせ8書体が `fonts` に生成されます（各TTFとWOFF2）。全8フェイスを含むTrueType Collection `NGSNoct.ttc` も生成します。

- `fonts/NGSNoctM.ttf` と `fonts/NGSNoctM.woff2` (フォント名: `NGS Noct M`)
- `fonts/NGSNoctP.ttf` と `fonts/NGSNoctP.woff2` (フォント名: `NGS Noct P`)
- `NGSNoctMF` / `NGSNoctPF` は低背版です。`lowercase_mf` / `lowercase_pf` の専用 `g/p/q` を使い、通常版よりフォント垂直メトリクスをY座標2単位（400 units）低くします。MFの等幅送り幅は500 unitsです。
- `-Bold` は線幅を太くしたBoldウェイトです。Regularと別ファイルとして生成します。

各フォントには、空白、数字、大文字、小文字、および指定した45記号が入ります。TTFはパソコンへのインストール用、WOFF2はWebページでの使用に適した形式です。TTCは8フェイスをまとめてインストールする形式です。等幅またはプロポーショナルだけを作る場合は、`build_fonts.py` に `--variant lc1` または `--variant lc2` を指定してください。指定した幅種のRegular/BoldとMF/PFを生成します。

字形SVGは `src/charsvg/` 配下のサブディレクトリ（`digits`, `uppercase`, `lowercase_m`, `lowercase_p`, `lowercase_mf`, `lowercase_pf`, `symbols`）に配置します。ファイル名は文字とUnicodeコードポイント（例: `A_0041.svg`）とし、Windowsのファイル名に使えない文字はコードポイント名（例: `__002F.svg`）にします。全字の表示枠は `120×256px`, `viewBox="-0.5 0.8 3 6.4"` に統一し、40pxを格子座標1つに対応させます。字形の横方向の輪郭中心は `X=1` とし、配置オフセットは丸め前の原稿形状から求めます。パス座標は主にグリッド整数とし、曲線端点や短い点画は0.25刻みに揃えます。原稿の基線位置に合わせて各字を配置し、フォント基線`Y=5`に揃えます。下がり部分はY=7まで使えます。各字形は1つのpathにまとめ、d属性はコマンドごとに改行します。曲線はベジェではなく円弧の A コマンドで出力し、円弧半径は0.25刻みに揃えます。

LC1は空白を含むすべての文字の送り幅を500 unitsに統一した等幅です。LC2は字形の幅に合わせて送り幅を変えるプロポーショナルです。線画はフォントで扱える塗りつぶし輪郭に変換してから収録します。

記号45字のうち37字はグループ、8字は単独図形です。さらに、1本だけグループ外にある線は接している記号の一部として自動で取り込みます。

収録文字と記号の図面上の並びは [FONT_CHARACTERS.md](FONT_CHARACTERS.md) を参照してください。

## GitHub Releases

`../.github/workflows/release-fonts.yml` は `v1.2.3` のようなタグをpushすると実行されます。8書体のフォント・108文字・等幅/プロポーショナル・ウェイト・垂直メトリクスを検証してから、各TTF/WOFF2をGitHub Releaseへ添付します。

- `NGS-Noct-v1.2.3.zip` (8書体のTTF/WOFF2、全書体入りTTC、収録文字一覧)
- `NGS-Noct.zip` (最新版への固定名リンク)
- M/P/MF/PF、Regular/Bold各書体のTTF/WOFF2と全8書体TTC
- `SHA256SUMS.txt`

リリース梱包処理は `tools/build_release.py` です。

公開時は、作成したバージョンに合わせてタグを付けてpushします。

```powershell
git tag v1.0.0
git push origin v1.0.0
```

この作業環境のNGSCSFontにはGit remoteが設定されていないため、実際にReleaseを公開する前にGitHubリポジトリのremoteを設定してください。また、リポジトリにライセンスファイルがないため、公開前に配布条件を決めてライセンスを追加してください。
