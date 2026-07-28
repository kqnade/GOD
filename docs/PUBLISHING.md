# 公開前チェックリスト

このリポジトリには、公開可能なソースコードと、公開してはいけない運用
データが同じ作業ディレクトリに存在し得ます。GitHubなどへ公開する前に、
次を確認してください。

## 必須

- [ ] `.env`がGitの追跡対象に含まれていない
- [ ] `data/`、SQLiteファイル、ログが追跡対象に含まれていない
- [ ] DiscordのBot Token、Webhook URL、サーバーID、チャンネルID、
      ユーザーIDがソースやGit履歴に含まれていない
- [ ] `git diff --cached`で公開予定の全内容を確認した
- [ ] `python -m unittest discover -s tests -v`が成功する
- [ ] Discordサーバーの参加者から、会話を保存することへの同意を得ている
- [ ] ルートの`LICENSE`と、コーパスへ適用される別ライセンスを確認した

## 推奨

- [ ] GitHubのSecret scanningとPush protectionを有効にした
- [ ] GitHubのPrivate vulnerability reportingを有効にした
- [ ] Renovate Appをリポジトリで有効化し、Dependency Dashboardが作成
      されることを確認した
- [ ] 公開リポジトリ用の連絡先と行動規範を用意した

## 公開対象の確認例

```bash
git status --short
git ls-files
git diff --cached --stat
git grep -n -I -E 'DISCORD_TOKEN=.+|discord(app)?\.com/api/webhooks'
```

`.gitignore`は、すでにGitへ追加済みのファイルを追跡対象から外しません。
誤って秘密情報をコミットした場合は、単にファイルを削除するだけではGit
履歴に残ります。Tokenを直ちに失効・再発行し、履歴の除去も行ってください。

## ライセンス

`corpus/real_persona_chat.txt`は、コードとは別にCC BY-SA 4.0で提供される
派生データです。詳細は`corpus/README.md`と
`corpus/REAL_PERSONA_CHAT_LICENSE.txt`を参照してください。

コード本体は、ルートの`LICENSE`に記載されたMIT Licenseで提供されます。
第三者由来のコーパスにはMIT Licenseではなく、上記のCC BY-SA 4.0が適用
されます。
