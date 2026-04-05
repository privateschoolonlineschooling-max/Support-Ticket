# 🎫 Discord Ticket Bot

A feature-rich Discord ticket bot with categories, question modals, claim system, and closure requests.

## Features

- **5 Ticket Categories**: Administrator, Report Player, In-Game Appeals, Support, Other
- **Question Modals**: Each category has specific questions answered via Discord modals
- **Private Channels**: Tickets are created as private channels visible only to the opener and staff
- **Claim System**: Staff can claim tickets (opener cannot claim their own)
- **Close Protection**: Ticket openers cannot close their own tickets
- **Closure Requests**: Staff can request closure with Accept/Deny buttons
- **Transcripts**: Generates transcripts on ticket close

## Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/ticket_setup` | Posts the ticket panel with category buttons | Manage Channels |
| `/closure_request` | Request to close the current ticket | Claimer/Staff |
| `/add_user` | Add a user to the current ticket | Manage Channels |
| `/remove_user` | Remove a user from the current ticket | Manage Channels |
| `/rename_ticket` | Rename the current ticket channel | Manage Channels |
| `/ticket_stats` | View open ticket statistics | Manage Channels |

## Setup

### 1. Create a Discord Bot
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → copy the **token**
3. Enable **Message Content Intent** and **Server Members Intent**
4. Invite the bot with `applications.commands` and `bot` scopes (Administrator permission recommended)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Set Environment Variable
```bash
# Linux/Mac
export DISCORD_BOT_TOKEN=your_token_here

# Windows CMD
set DISCORD_BOT_TOKEN=your_token_here

# Windows PowerShell
$env:DISCORD_BOT_TOKEN="your_token_here"
```

### 4. Run the Bot
```bash
python ticket_bot.py
```

## Optional Configuration

In `ticket_bot.py`, you can set:
- `TRANSCRIPT_CHANNEL_ID` — Channel ID to send ticket transcripts to

## License

MIT
