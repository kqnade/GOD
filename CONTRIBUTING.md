# Contributing

IssueやPull Requestを歓迎します。会話データ、DiscordのユーザーID、Bot
Tokenなど、第三者の情報や秘密情報は投稿しないでください。

## 開発環境

Python 3.11以上と[uv](https://docs.astral.sh/uv/)を用意し、リポジトリの
ルートで次を実行します。

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run ruff check .
```

Botを実際に起動する場合だけ、`.env.example` を `.env` へコピーして設定
してください。テストに本物のDiscord認証情報は不要です。

## Pull Request

- 変更の目的と、利用者から見た影響を説明してください。
- 振る舞いを変える場合はテストを追加または更新してください。
- READMEや設定例に影響する場合は、コードと同時に更新してください。
- 依存関係を変える場合は`uv lock`を実行し、`uv.lock`も更新してください。
- `data/`、`.env`、ログ、ローカルのコーパスをコミットしないでください。

コーパスを変更する場合は、由来、取得日、加工内容、ライセンスを
`corpus/README.md` に記録してください。
