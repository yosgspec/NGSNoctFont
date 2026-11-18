# フォントの作成方法

グループ化したSVG字形から、lc1版とlc2版の両方を作成します。

```powershell
python -m pip install -r requirements-fonts.txt
python split_glyphs.py --overwrite
python build_fonts.py
```

次の4ファイルが生成されます。

- `fonts/NGSCSFont-LC1-Mono.ttf` と `fonts/NGSCSFont-LC1-Mono.woff2`
- `fonts/NGSCSFont-LC2-Mono.ttf` と `fonts/NGSCSFont-LC2-Mono.woff2`

各フォントには、空白、数字、大文字、およびlc1またはlc2の小文字が入ります。TTFはパソコンへのインストール用、WOFF2はWebページでの使用に適した形式です。片方だけ作る場合は、`build_fonts.py` に `--variant lc1` または `--variant lc2` を指定してください。

空白を含むすべての文字の送り幅は、1000 units/em中の500 unitsで統一しています。字形はセルの中央に配置し、左右の余白を抑えています。線画は、フォントで扱える塗りつぶし輪郭に変換してから収録します。

収録済み文字と、今後追加する記号の一覧は [FONT_CHARACTERS.md](FONT_CHARACTERS.md) を参照してください。