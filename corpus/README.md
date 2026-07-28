# Corpus attribution

`real_persona_chat.txt` is a format-converted derivative of
[RealPersonaChat](https://github.com/nu-dialogue/real-persona-chat), created by
the Dialogue Systems Lab at Nagoya University.

- Source version: public repository `main` branch, retrieved 2026-07-27
- Source statistics: 13,583 dialogues and 408,619 utterances
- License: Creative Commons Attribution-ShareAlike 4.0 International
- Changes: extracted utterance text from JSON, normalized Unicode and
  whitespace, removed URLs, email addresses, secrets-like text, empty lines,
  and utterances over 20 characters; converted to
  `dialogue_id<TAB>utterance` format

The converted corpus remains available under CC BY-SA 4.0. See
`REAL_PERSONA_CHAT_LICENSE.txt` for the license text. The small
`default.txt` corpus is original project material and is used only when
configured explicitly.
