# DDPER Player Telegram Bot

Telegram bot that reads and displays publicly visible information from a DDPER player profile.

## Railway

- Repository: `sinfxi/fxi-store`
- Branch: `ddper-player-bot`
- Root Directory: `/ddper_player_bot`
- Start Command: `python main.py`
- Required variable: `BOT_TOKEN` (create/regenerate it with BotFather; never commit it)
- Optional variable: `DDPER_PLAYER_URL` (defaults to `https://ddper.ir/players/fxi#gores`)
- Optional variable: `ADMIN_ID` (defaults to `6384557276`; reserved for future admin-only features)

Commands: `/start`, `/profile`, `/player fxi`.

The bot uses the public page only. If DDPER renders profile statistics in client-side JavaScript or blocks automated requests, only visible HTML metadata/text can be extracted until a supported public API is identified.
