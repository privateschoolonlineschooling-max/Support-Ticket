# 🎫 Discord Ticket Bot

A feature-rich Discord ticket bot with categories, question modals, claim system, status tracking, and feedback collection.

## Features

- **5 Ticket Categories**: Administrator, Report Player, In-Game Appeals, Support, Other
- **Question Modals**: Each category has specific questions answered via Discord modals
- **Private Channels**: Tickets are created as private channels visible only to the opener and staff
- **Claim System**: Staff can claim tickets (opener cannot claim their own)
- **Close Protection**: Ticket openers cannot close their own tickets
- **Ticket Status Tracking**: Change ticket status between `open`, `pending`, and `closed`
- **Idle Tracking**: Mark tickets as inactive/idle for monitoring
- **Smart Reminders**: Send reminders to staff or ticket openers about inactive tickets
- **Auto-Close**: Automatically close tickets after specified time (minutes/hours)
- **Feedback System**: Users can rate their support experience (1-5 stars) after ticket closure
- **Ticket History**: View complete ticket history for any user with ratings and details
- **Blacklist System**: Prevent users from opening tickets
- **Announcement System**: Create and post announcements to specific channels
- **Closure Requests**: Staff can request closure with Accept/Deny buttons
- **Activity Tracking**: Automatic tracking of last activity timestamps

## Commands

### Ticket Management
| Command | Description | Permission |
|---------|-------------|------------|
| `/ticket_setup` | Posts the ticket panel with category buttons | Manage Channels |
| `/status <open/pending/closed>` | Change the current ticket status | Manage Channels |
| `/idle` | Mark ticket as inactive | Manage Channels |
| `/remind <staff/user>` | Send reminder about ticket inactivity | Manage Channels |
| `/auto-close <time_value> <minutes/hours>` | Schedule automatic ticket closure | Manage Channels |
| `/feedback` | Rate your support experience (1-5 stars) | Any User |
| `/history @user` | View ticket history for a user | Manage Channels |

### Ticket Control
| Command | Description | Permission |
|---------|-------------|------------|
| `/closure_request` | Request to close the current ticket | Claimer/Staff |
| `/add_user @user` | Add a user to the current ticket | Manage Channels |
| `/remove_user @user` | Remove a user from the current ticket | Manage Channels |
| `/rename_ticket <name>` | Rename the current ticket channel | Manage Channels |
| `/ticket_stats` | View open ticket statistics | Manage Channels |

### Admin Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `/blacklist @user <reason>` | Blacklist a user from opening tickets | Manage Channels |
| `/unblacklist @user` | Remove a user from the blacklist | Manage Channels |
| `/blacklist_list` | View the blacklist | Manage Channels |
| `/announce` | Create an announcement and post to a channel | Manage Server |

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

## New Features Details

### 📊 Status Tracking
- Change ticket status using `/status <open|pending|closed>`
- Helps organize and track ticket workflow
- Status is displayed when tickets are closed

### 😴 Idle Management
- Mark tickets as inactive using `/idle`
- Great for monitoring slow-moving tickets
- Works with reminder system

### 🔔 Smart Reminders
- Ping staff about inactive tickets: `/remind staff`
- Notify users about their tickets: `/remind user`
- 5-minute cooldown between reminders to prevent spam

### ⏰ Auto-Close
- Enable auto-closing: `/auto-close 30 minutes` or `/auto-close 2 hours`
- Tickets automatically delete after specified time
- Background task checks every minute

### ⭐ Feedback System
- Users get DM with feedback link when tickets close
- Rate experience 1-5 stars with optional comments
- Ratings stored in ticket history for analytics

### 📋 History Tracking
- View all tickets from any user: `/history @user`
- Shows ticket category, dates, status, and feedback ratings
- Last 10 tickets displayed for easy review
- Automatic history creation on ticket closure

## Data Storage

The bot creates and maintains three JSON files:

1. **tickets.json** - Current open tickets with status, activity, and auto-close info
2. **ticket_history.json** - Closed ticket history with user feedback ratings
3. **blacklist.json** - Blacklisted users and reasons

All data is automatically saved and loaded on bot startup.

## Optional Configuration

In `ticket_bot.py`, you can set:
- `TRANSCRIPT_CHANNEL_ID` — Channel ID to send ticket transcripts to
- `KASI_VIBES_GUILD_ID` — Specific guild for ticket logging
- `KASI_VIBES_DATA_CHANNEL_ID` — Data logging channel

## Error Handling & Bug Prevention

✅ **Safe Data Handling**: All JSON operations use try-catch with fallback defaults
✅ **No Lost Data**: Automatic saves on every state change
✅ **Rate Limiting**: 5-minute cooldown on reminders to prevent spam
✅ **Input Validation**: All user inputs validated before processing
✅ **Graceful Failures**: Bot continues running even if a ticket operation fails
✅ **Duplicate Prevention**: Checks prevent users from having multiple open tickets
✅ **Permission Checks**: Staff-only commands verify manage_channels permission
✅ **Async Safety**: All Discord operations properly await and handle exceptions

## License

MIT
