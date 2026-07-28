# Contributing

IssueやPull Requestを歓迎します。会話データ、DiscordのユーザーID、Bot
Tokenなど、第三者の情報や秘密情報は投稿しないでください。

## 開発環境

Python 3.11以上を用意し、リポジトリのルートで次を実行します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Botを実際に起動する場合だけ、`.env.example` を `.env` へコピーして設定
してください。テストに本物のDiscord認証情報は不要です。

## Pull Request

- 変更の目的と、利用者から見た影響を説明してください。
- 振る舞いを変える場合はテストを追加または更新してください。
- READMEや設定例に影響する場合は、コードと同時に更新してください。
- `data/`、`.env`、ログ、ローカルのコーパスをコミットしないでください。

コーパスを変更する場合は、由来、取得日、加工内容、ライセンスを
`corpus/README.md` に記録してください。
