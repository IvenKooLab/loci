<p align="center">
  <img src="docs/assets/loci-banner.svg" alt="loci — shared memory for your AI tools" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/IvenKooLab/loci/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/IvenKooLab/loci/ci.yml?branch=main&amp;label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/loci-rag/"><img src="https://img.shields.io/pypi/v/loci-rag?color=367d65" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-367d65" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-367d65" alt="MIT license"></a>
</p>

**散らばったノート、プロジェクト文書、Agent の記憶を、検索・質問・出典確認ができる知識ベースに。ターミナル、ブラウザー、MCP クライアントから使えます。**

loci はベクトル検索と BM25 を組み合わせ、回答に「ファイル > セクション」の引用を付けます。ファイルとインデックスはローカルに保存され、埋め込みとチャットのリクエストは設定したサービスに送信されます。ローカルモデルでオフライン運用することもできます。

[クイックスタート](#クイックスタート) · [Web コンソール](#web-コンソール) · [AI ツールとの接続](#ai-ツールとの接続) · [詳細ガイド（英語）](docs/guide.en.md)

![loci コンソールと記憶ファイルのプレビュー](docs/assets/console-demo-light.png)

*実際の UI を架空のデモデータで撮影しています。個人の知識ベース、アカウント、API キーには接続していません。件数は説明用の値です。*

<details>
<summary>ダークテーマのプレビュー</summary>

![loci console — dark theme, fictional demo data](docs/assets/console-demo-dark.png)

</details>

## できること

| 目的 | loci の機能 |
|---|---|
| 過去の意思決定を探す | ディレクトリを横断するハイブリッド検索。タグ・パス・日付で絞り込み |
| 回答の根拠を確認する | セクション単位の引用と、任意の主張別検証 |
| AI ツールを切り替えても文脈を保つ | MCP で同じインスタンスを共有。長期記憶は Markdown で保存 |
| 各 Agent の記憶を把握する | harness の自動検出、ファイル閲覧、統計、要約 |
| 画面から知識ベースを管理する | 検索、質問、記憶の編集、インデックス更新、監査ログ |

Markdown、テキスト、HTML、org-mode、チャットのエクスポートに標準対応。PDF、Word、OCR はオプションです。既存のエディターや Obsidian vault もそのまま使えます。

## クイックスタート

**Python 3.11+** が必要です。設定例を含むソースから始める場合：

```bash
git clone https://github.com/IvenKooLab/loci.git
cd loci
python -m pip install -e .
cp config.example.toml config.toml
```

`config.toml` の `[llm]`、`[embed]` を設定し、`[[sources]].path` をノートのディレクトリに変更します。埋め込みサービスには `/embeddings` が必要です。チャットと埋め込みに別々のプロバイダーを使えます。

```bash
loci ingest
loci search "デプロイの決定"
loci ask "デプロイ方法はどう決めましたか？その理由は？"
```

設定済みなら `python -m pip install loci-rag` でインストールし、`LOCI_HOME` でインスタンスのディレクトリを指定できます。PDF・Word 対応：`python -m pip install 'loci-rag[pdf,docx]'`。

> キーは `BRAIN_LLM_API_KEY`、`BRAIN_EMBED_API_KEY` でも指定できます。埋め込みモデルの変更後は `loci ingest --force` で再構築してください。

## Web コンソール

```bash
loci serve-http
```

**[127.0.0.1:8765/ui](http://127.0.0.1:8765/ui)** を開きます。UI は英語・簡体字中国語、ライト・ダークの切り替えに対応。フロントエンドのビルドは不要です。

初期設定ではループバックからの匿名接続に管理者権限を付与します。リバースプロキシや SSH トンネル経由では `[http] local_admin = false` とロール別トークンを設定してください。[アクセス制御（英語）](docs/guide.en.md#web-console)。

DeepSeek Harness では [loci-dsh](https://github.com/IvenKooLab/loci-dsh) を使い、同じ HTTP バックエンドの検索・質問・記憶の保存をワークベンチに追加できます。

## AI ツールとの接続

MCP クライアントで**同じ `LOCI_HOME`** を指定すると、設定・インデックス・記憶を共有できます。

```json
{
  "mcpServers": {
    "loci": {
      "command": "loci-mcp",
      "env": { "LOCI_HOME": "/absolute/path/to/your/loci-instance" }
    }
  }
}
```

ディレクトリには `config.toml` を置いてください。`loci-mcp` が見つからない場合は実行ファイルの絶対パスを指定します。

| MCP ツール | 用途 |
|---|---|
| `brain_search` · `brain_ask` | 検索と出典付きの回答 |
| `brain_remember` · `brain_forget` | 長期記憶の保存と撤回 |
| `brain_links` · `brain_graph` | ノートリンクと知識の関係を調べる |
| `brain_wiki` · `brain_harness` | 知識の整理と Agent の記憶管理 |
| `brain_stats` · `brain_ingest` | インデックスの確認と更新 |

## 日々の使い方

```bash
loci watch
loci remember "デモにはステージング環境を使う" --title "デモ環境の決定"
loci search "デモ環境" --tag memory
loci ask "デモの準備で注意することは？" --verify
loci harness
```

変更されたファイルを差分でインデックス化し、記憶は読みやすい Markdown のまま保存します。複数のマシンでは元ファイルと記憶を同期し、インデックスは各マシンで再構築してください。認証情報はリポジトリに保存しないでください。

## ドキュメント

[使用ガイド（英語）](docs/guide.en.md) · [設定例](config.example.toml) · [アーキテクチャ](docs/ARCHITECTURE.md) · [変更履歴](CHANGELOG.md) · [ロードマップ](docs/roadmap.md) · [コントリビューション](CONTRIBUTING.md)

実行時には OpenAI 互換 SDK と ChromaDB を使用し、LangChain や LlamaIndex には依存しません。テストは API キーなしでオフライン実行できます。

```bash
python -m pip install -e '.[dev,pdf]'
pytest
```

[GitHub](https://github.com/IvenKooLab/loci) · [Gitee](https://gitee.com/IvenKooLab/loci) · [MIT](LICENSE)
