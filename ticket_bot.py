import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import json
import os
import io

# ─── Config ───
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TICKET_LOG_CHANNEL_ID = None  # Set to a channel ID for ticket logs
TRANSCRIPT_CHANNEL_ID = None  # Set to a channel ID for transcripts

# Specific config for Kasi Vibes Studios server
KASI_VIBES_GUILD_ID = 1386401415953518613
KASI_VIBES_DATA_CHANNEL_ID = 1422680594646700073

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─── In-memory ticket store ───
# ticket_channel_id -> { "opener": user_id, "claimer": user_id|None, "category": str, "answers": dict,
#                        "status": "open|pending|closed", "created_at": str, "last_activity": str, 
#                        "idle": bool, "auto_close_time": int|None, "logged": bool }
tickets = {}
TICKET_STORE_FILE = os.path.join(os.path.dirname(__file__), "tickets.json")

# ─── Ticket history store ───
# user_id -> [{ "ticket_id": int, "category": str, "created_at": str, "closed_at": str, "feedback_rating": int|None }]
ticket_history = {}
HISTORY_STORE_FILE = os.path.join(os.path.dirname(__file__), "ticket_history.json")

# ─── Blacklist store ───
# user_id -> { "blacklisted_by": user_id, "reason": str, "timestamp": str }
blacklist = {}
BLACKLIST_STORE_FILE = os.path.join(os.path.dirname(__file__), "blacklist.json")

# ─── Pending reminders ───
# ticket_channel_id -> { "reminded_at": str, "type": "staff|user" }
reminders = {}


def save_ticket_store() -> None:
    try:
        with open(TICKET_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in tickets.items()}, f, indent=2)
    except OSError:
        pass


def load_ticket_store() -> None:
    if not os.path.exists(TICKET_STORE_FILE):
        return
    try:
        with open(TICKET_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for key, value in data.items():
                tickets[int(key)] = value
    except (OSError, json.JSONDecodeError):
        pass


def save_history_store() -> None:
    try:
        with open(HISTORY_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in ticket_history.items()}, f, indent=2)
    except OSError:
        pass


def load_history_store() -> None:
    if not os.path.exists(HISTORY_STORE_FILE):
        return
    try:
        with open(HISTORY_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for key, value in data.items():
                ticket_history[int(key)] = value
    except (OSError, json.JSONDecodeError):
        pass


def save_blacklist_store() -> None:
    try:
        with open(BLACKLIST_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in blacklist.items()}, f, indent=2)
    except OSError:
        pass


def load_blacklist_store() -> None:
    if not os.path.exists(BLACKLIST_STORE_FILE):
        return
    try:
        with open(BLACKLIST_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for key, value in data.items():
                blacklist[int(key)] = value
    except (OSError, json.JSONDecodeError):
        pass


def is_staff_member(member: discord.Member) -> bool:
    return member.guild_permissions.manage_channels if isinstance(member, discord.Member) else False


def get_ticket_data(channel: discord.TextChannel):
    data = tickets.get(channel.id)
    if data:
        return data
    if isinstance(channel, discord.TextChannel) and channel.name.startswith("ticket-"):
        opener = None
        claimer = None
        category = "Unknown"
        if channel.topic and channel.topic.startswith("ticket_data:"):
            try:
                payload = json.loads(channel.topic[len("ticket_data:"):])
                opener = payload.get("opener")
                claimer = payload.get("claimer")
                category = payload.get("category", "Unknown")
            except json.JSONDecodeError:
                pass

        current_time = datetime.datetime.utcnow().isoformat()
        data = {
            "opener": opener,
            "claimer": claimer,
            "category": category,
            "answers": {},
            "status": "open",
            "created_at": current_time,
            "last_activity": current_time,
            "idle": False,
            "auto_close_time": None,
            "logged": True,
        }
        tickets[channel.id] = data
        save_ticket_store()
        return data
    return None


# ─── Colors ───
COLORS = {
    "Administrator": discord.Color.red(),
    "Report Player": discord.Color.blue(),
    "In-Game Appeals": discord.Color.green(),
    "Support": discord.Color.from_rgb(0, 0, 0),
    "Other": discord.Color.from_rgb(255, 255, 255),
}

# ─── Questions per category ───
QUESTIONS = {
    "Administrator": [
        "What is your in-game name?",
        "What administrative issue are you experiencing?",
        "Please provide any relevant details or evidence.",
    ],
    "Report Player": [
        "What is your in-game name?",
        "What is the name of the player you are reporting?",
        "What rule did they break?",
        "Do you have any evidence (screenshots/videos)?",
    ],
    "In-Game Appeals": [
        "What is your in-game name?",
        "What were you punished for?",
        "Why do you believe your punishment should be lifted?",
        "Any additional context?",
    ],
    "Support": [
        "What is your in-game name?",
        "Describe the issue you need help with.",
        "Have you tried any troubleshooting steps?",
    ],
    "Other": [
        "What is your in-game name?",
        "Please describe your inquiry in detail.",
    ],
}


# ═══════════════════════════════════════════
#  TICKET SETUP PANEL
# ═══════════════════════════════════════════

class TicketSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔴 Administrator", style=discord.ButtonStyle.danger, custom_id="ticket_administrator", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket_flow(interaction, "Administrator")

    @discord.ui.button(label="🔵 Report Player", style=discord.ButtonStyle.primary, custom_id="ticket_report", row=0)
    async def report_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket_flow(interaction, "Report Player")

    @discord.ui.button(label="🟢 In-Game Appeals", style=discord.ButtonStyle.success, custom_id="ticket_appeals", row=1)
    async def appeals_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket_flow(interaction, "In-Game Appeals")

    @discord.ui.button(label="⚫ Support", style=discord.ButtonStyle.secondary, custom_id="ticket_support", row=1)
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket_flow(interaction, "Support")

    @discord.ui.button(label="⚪ Other", style=discord.ButtonStyle.secondary, custom_id="ticket_other", row=2)
    async def other_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket_flow(interaction, "Other")


# ═══════════════════════════════════════════
#  QUESTION MODAL
# ═══════════════════════════════════════════

class TicketQuestionsModal(discord.ui.Modal):
    def __init__(self, category: str):
        super().__init__(title=f"{category} Ticket")
        self.category = category
        self.fields_list = []
        questions = QUESTIONS[category]
        for i, q in enumerate(questions[:5]):  # Modal supports max 5 fields
            field = discord.ui.TextInput(
                label=q[:45],
                style=discord.TextStyle.paragraph if len(q) > 30 else discord.TextStyle.short,
                required=True,
                max_length=1024,
            )
            self.add_item(field)
            self.fields_list.append((q, field))

    async def on_submit(self, interaction: discord.Interaction):
        answers = {q: f.value for q, f in self.fields_list}
        await create_ticket_channel(interaction, self.category, answers)


# ═══════════════════════════════════════════
#  TICKET CHANNEL CREATION
# ═══════════════════════════════════════════

async def open_ticket_flow(interaction: discord.Interaction, category: str):
    # Check if user is blacklisted
    if interaction.user.id in blacklist:
        await interaction.response.send_message(
            "❌ You are blacklisted from opening tickets.", ephemeral=True
        )
        return
    
    # Check if user already has an open ticket
    for ch_id, data in tickets.items():
        if data["opener"] == interaction.user.id:
            await interaction.response.send_message(
                f"❌ You already have an open ticket: <#{ch_id}>", ephemeral=True
            )
            return
    modal = TicketQuestionsModal(category)
    await interaction.response.send_modal(modal)


async def create_ticket_channel(interaction: discord.Interaction, category: str, answers: dict):
    guild = interaction.guild
    user = interaction.user

    # Find or create ticket category channel
    category_channel = discord.utils.get(guild.categories, name="📩 Tickets")
    if not category_channel:
        # Staff role = anyone with manage_channels (Discord Administration)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        category_channel = await guild.create_category("📩 Tickets", overwrites=overwrites)

    # Create private channel
    ticket_name = f"ticket-{user.name}-{len(tickets) + 1}"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
    }
    # Grant access to staff (users with manage_channels)
    for role in guild.roles:
        if role.permissions.manage_channels and role != guild.default_role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    channel = await guild.create_text_channel(
        ticket_name, category=category_channel, overwrites=overwrites
    )

    current_time = datetime.datetime.utcnow().isoformat()
    tickets[channel.id] = {
        "opener": user.id,
        "claimer": None,
        "category": category,
        "answers": answers,
        "status": "open",
        "created_at": current_time,
        "last_activity": current_time,
        "idle": False,
        "auto_close_time": None,
        "logged": False,
    }
    save_ticket_store()
    await channel.edit(topic=f"ticket_data:{json.dumps({'opener': user.id, 'claimer': None, 'category': category})}")

    # Build answers embed
    color = COLORS.get(category, discord.Color.blurple())
    embed = discord.Embed(
        title=f"📩 {category} Ticket",
        description=f"Ticket opened by {user.mention}\nPlease wait for a staff member to assist you.",
        color=color,
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text=f"Ticket ID: {channel.id}")
    for q, a in answers.items():
        embed.add_field(name=q, value=a, inline=False)

    await channel.send(embed=embed, view=TicketControlView())

    await interaction.response.send_message(
        f"✅ Your ticket has been created: {channel.mention}", ephemeral=True
    )


async def send_ticket_log(guild: discord.Guild, data: dict, ticket_channel: discord.TextChannel):
    if guild.id != KASI_VIBES_GUILD_ID:
        return

    log_channel = guild.get_channel(KASI_VIBES_DATA_CHANNEL_ID)
    if not log_channel:
        return

    opener = guild.get_member(data["opener"])
    opener_text = opener.mention if opener else f"<@{data['opener']}>"

    embed = discord.Embed(
        title="📥 Ticket Log Entry",
        description=(
            f"**Ticket Channel:** {ticket_channel.mention}\n"
            f"**Opened by:** {opener_text}\n"
            f"**Category:** {data['category']}"
        ),
        color=COLORS.get(data["category"], discord.Color.blurple()),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text=f"Ticket ID: {ticket_channel.id}")

    lines = []
    for q, a in data["answers"].items():
        lines.append(f"{q}: {a}")

    if lines:
        file = discord.File(
            fp=io.BytesIO("\n".join(lines).encode()),
            filename=f"ticket-{ticket_channel.id}-details.txt",
        )
        await log_channel.send(embed=embed, file=file)
    else:
        await log_channel.send(embed=embed)


class AnnouncementChannelSelect(discord.ui.Select):
    def __init__(self, announcement: str, author_id: int, channels, title: str = "📢 Announcement"):
        options = []
        for channel in channels[:25]:
            options.append(
                discord.SelectOption(
                    label=channel.name,
                    value=str(channel.id),
                    description=f"#{channel.name}"[:100],
                )
            )
        super().__init__(
            placeholder="Select a channel to post the announcement",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="announcement_channel_select",
        )
        self.announcement = announcement
        self.author_id = author_id
        self.title = title

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "❌ Only the user who started the announcement can choose the channel.",
                ephemeral=True,
            )

        channel_id = int(self.values[0])
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            return await interaction.response.send_message(
                "❌ Could not find the selected channel.", ephemeral=True
            )

        embed = discord.Embed(
            title=self.title,
            description=self.announcement,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_footer(text=f"Posted by {interaction.user}")
        await channel.send(embed=embed)
        await interaction.response.edit_message(
            content=f"✅ Announcement sent to {channel.mention}.", embed=None, view=None
        )
        self.view.stop()


class AnnouncementSelectView(discord.ui.View):
    def __init__(self, announcement: str, author_id: int, channels, title: str = "📢 Announcement"):
        super().__init__(timeout=120)
        self.add_item(AnnouncementChannelSelect(announcement, author_id, channels, title))


class AnnouncementModal(discord.ui.Modal, title="Create Announcement"):
    title_input = discord.ui.TextInput(
        label="Announcement title",
        style=discord.TextStyle.short,
        required=False,
        max_length=100,
        placeholder="Leave blank for default '📢 Announcement'",
    )
    announcement = discord.ui.TextInput(
        label="Announcement text",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
        placeholder="Write the announcement message here",
    )

    async def on_submit(self, interaction: discord.Interaction):
        channels = [
            c for c in interaction.guild.text_channels
            if c.permissions_for(interaction.guild.me).send_messages
        ]
        if not channels:
            return await interaction.response.send_message(
                "❌ I couldn't find any channels to post announcements in.",
                ephemeral=True,
            )

        announcement = self.announcement.value
        title = self.title_input.value or "📢 Announcement"
        await interaction.response.send_message(
            "Select the channel you want to post the announcement in:",
            view=AnnouncementSelectView(announcement, interaction.user.id, channels, title),
            ephemeral=True,
        )


# ═══════════════════════════════════════════
#  TICKET CONTROL BUTTONS (inside ticket)
# ═══════════════════════════════════════════

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_ticket_data(interaction.channel)
        if not data:
            return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
        if data.get("opener") and interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot close your own ticket.", ephemeral=True)
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        await close_ticket(interaction, reason=None)

    @discord.ui.button(label="🔒 Close With Reason", style=discord.ButtonStyle.danger, custom_id="ticket_close_reason")
    async def close_reason_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_ticket_data(interaction.channel)
        if not data:
            return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
        if data.get("opener") and interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot close your own ticket.", ephemeral=True)
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        await interaction.response.send_modal(CloseReasonModal())

    @discord.ui.button(label="🙋 Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_ticket_data(interaction.channel)
        if not data:
            return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
        if data.get("opener") and interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot claim your own ticket.", ephemeral=True)
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        if data["claimer"]:
            return await interaction.response.send_message(f"❌ Already claimed by <@{data['claimer']}>.", ephemeral=True)
        data["claimer"] = interaction.user.id
        save_ticket_store()
        await interaction.channel.edit(topic=f"ticket_data:{json.dumps({'opener': data['opener'], 'claimer': data['claimer'], 'category': data['category']})}")
        
        # Send ticket log if applicable
        if not data.get("logged", False):
            await send_ticket_log(interaction.guild, data, interaction.channel)
            data["logged"] = True
            save_ticket_store()
        
        embed = discord.Embed(
            title="🙋 Ticket Claimed",
            description=f"This ticket has been claimed by {interaction.user.mention}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)


class CloseReasonModal(discord.ui.Modal, title="Close Ticket"):
    reason = discord.ui.TextInput(label="Reason for closing", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await close_ticket(interaction, reason=self.reason.value)


# ═══════════════════════════════════════════
#  FEEDBACK MODAL
# ═══════════════════════════════════════════

class FeedbackModal(discord.ui.Modal, title="Rate Your Support Experience"):
    rating = discord.ui.TextInput(
        label="Rating (1-5 stars)",
        placeholder="Enter a number from 1 to 5",
        style=discord.TextStyle.short,
        required=True,
        min_length=1,
        max_length=1
    )
    comments = discord.ui.TextInput(
        label="Additional comments (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rating = int(self.rating.value)
            if rating < 1 or rating > 5:
                await interaction.response.send_message("❌ Rating must be between 1 and 5.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Rating must be a number.", ephemeral=True)
            return
        
        # Store feedback - this would be in the ticket history
        embed = discord.Embed(
            title="✅ Feedback Submitted",
            description=f"Thank you for rating your support experience!",
            color=discord.Color.green(),
        )
        embed.add_field(name="Rating", value=f"⭐ {rating}/5", inline=True)
        if self.comments.value:
            embed.add_field(name="Comments", value=self.comments.value, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════
#  CLOSURE REQUEST (/closure_request)
# ═══════════════════════════════════════════

class ClosureRequestView(discord.ui.View):
    def __init__(self, requester_id: int, opener_id: int | None):
        super().__init__(timeout=None)
        self.requester_id = requester_id
        self.opener_id = opener_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="closure_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_ticket_data(interaction.channel)
        if not data or self.opener_id is None:
            return await interaction.response.send_message(
                "❌ Cannot process this closure request because the ticket opener is unknown.",
                ephemeral=True,
            )
        if interaction.user.id != self.opener_id:
            return await interaction.response.send_message(
                "❌ Only the ticket opener can accept or deny this closure request.",
                ephemeral=True,
            )
        await close_ticket(interaction, reason="Closure request accepted")

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="closure_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_ticket_data(interaction.channel)
        if not data or self.opener_id is None:
            return await interaction.response.send_message(
                "❌ Cannot process this closure request because the ticket opener is unknown.",
                ephemeral=True,
            )
        if interaction.user.id != self.opener_id:
            return await interaction.response.send_message(
                "❌ Only the ticket opener can accept or deny this closure request.",
                ephemeral=True,
            )
        embed = discord.Embed(
            title="❌ Closure Request Denied",
            description=f"The closure request has been denied by {interaction.user.mention}.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)
        self.stop()


# ═══════════════════════════════════════════
#  CLOSE TICKET HELPER
# ═══════════════════════════════════════════

async def close_ticket(interaction: discord.Interaction, reason: str = None):
    channel = interaction.channel
    data = tickets.get(channel.id)
    if data is None:
        data = get_ticket_data(channel)

    # Respond immediately to avoid interaction timeout
    embed = discord.Embed(
        title="🔒 Ticket Closed",
        description=f"Closed by {interaction.user.mention}",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow(),
    )
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    if data:
        embed.add_field(name="Category", value=data["category"], inline=True)
        embed.add_field(name="Status", value=data.get("status", "open"), inline=True)
        if data.get("opener") is not None:
            embed.add_field(name="Opened by", value=f"<@{data['opener']}>", inline=True)
        if data["claimer"]:
            embed.add_field(name="Claimed by", value=f"<@{data['claimer']}>", inline=True)

    try:
        await interaction.response.send_message(embed=embed)
    except discord.InteractionResponded:
        # If already responded, send as followup
        await interaction.followup.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Failed to send close confirmation: {e}")
        # Try followup as last resort
        try:
            await interaction.followup.send(embed=embed)
        except:
            pass

    # Send DM to ticket opener with feedback request
    if data and data.get("opener") is not None:
        opener = interaction.guild.get_member(data["opener"])
        if opener is None:
            try:
                opener = await bot.fetch_user(data["opener"])
            except discord.NotFound:
                opener = None

        if opener:
            dm_embed = discord.Embed(
                title=f"🔒 Your {data.get('category', 'Support')} Ticket Has Been Closed",
                description=(
                    f"Your ticket in {interaction.guild.name} has been closed by {interaction.user.mention}."
                ),
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow(),
            )
            if reason:
                dm_embed.add_field(name="Reason for Closure", value=reason, inline=False)
            
            dm_embed.add_field(
                name="📋 Feedback",
                value="Please use `/feedback` to rate your support experience.",
                inline=False
            )
            
            try:
                await opener.send(embed=dm_embed)
            except discord.Forbidden:
                print(f"Could not DM {opener}")
        
        # Add to ticket history
        if opener:
            closed_time = datetime.datetime.utcnow().isoformat()
            if opener.id not in ticket_history:
                ticket_history[opener.id] = []
            
            ticket_history[opener.id].append({
                "ticket_id": channel.id,
                "category": data.get("category", "Unknown"),
                "created_at": data.get("created_at", closed_time),
                "closed_at": closed_time,
                "feedback_rating": None,
                "status": "closed"
            })
            save_history_store()

    # Remove from tickets and reminders
    tickets.pop(channel.id, None)
    reminders.pop(channel.id, None)
    save_ticket_store()
    
    # Delete the channel after a short delay
    try:
        await discord.utils.sleep_until(datetime.datetime.utcnow() + datetime.timedelta(seconds=5))
        await channel.delete(reason=f"Ticket closed by {interaction.user}")
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Failed to delete ticket channel: {e}")
        # If we can't delete the channel, at least notify that the ticket is closed
        try:
            await channel.send("❌ Failed to delete this channel. Please contact an administrator.")
        except (discord.Forbidden, discord.HTTPException):
            pass


# ═══════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════

@bot.tree.command(name="announce", description="Create an announcement with a custom title and pick the channel to post it in")
@app_commands.default_permissions(manage_channels=True)
async def announce(interaction: discord.Interaction):
    await interaction.response.send_modal(AnnouncementModal())


@bot.tree.command(name="ticket_setup", description="Set up the ticket panel in this channel")
@app_commands.default_permissions(manage_channels=True)
async def ticket_setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Support Tickets",
        description=(
            "Click a button below to open a ticket.\n\n"
            "🔴 **Administrator** — For admin-related inquiries and requests\n"
            "🔵 **Report Player** — Report a player for rule violations\n"
            "🟢 **In-Game Appeals** — Appeal a ban, mute, or other punishment\n"
            "⚫ **Support** — General support and help\n"
            "⚪ **Other** — Anything else not listed above"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Our team will respond as soon as possible!")
    await interaction.response.send_message(embed=embed, view=TicketSetupView())


@bot.tree.command(name="closure_request", description="Request to close the current ticket")
async def closure_request(interaction: discord.Interaction):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    if data["opener"] is None:
        return await interaction.response.send_message(
            "❌ Closure requests cannot be processed because the ticket opener is unknown.",
            ephemeral=True,
        )
    if data["claimer"] != interaction.user.id and not interaction.user.guild_permissions.manage_channels:
        return await interaction.response.send_message("❌ Only the ticket claimer or staff can request closure.", ephemeral=True)

    embed = discord.Embed(
        title="🔒 Closure Request",
        description=(
            f"{interaction.user.mention} is requesting to close this ticket.\n"
            f"Only the ticket opener (<@{data['opener']}>) can accept or deny this request."
        ),
        color=discord.Color.orange(),
    )
    await interaction.response.send_message(embed=embed, view=ClosureRequestView(interaction.user.id, data["opener"]))


@bot.tree.command(name="add_user", description="Add a user to the current ticket")
@app_commands.describe(user="The user to add")
@app_commands.default_permissions(manage_channels=True)
async def add_user(interaction: discord.Interaction, user: discord.Member):
    data = tickets.get(interaction.channel.id)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(f"✅ {user.mention} has been added to the ticket.")


@bot.tree.command(name="remove_user", description="Remove a user from the current ticket")
@app_commands.describe(user="The user to remove")
@app_commands.default_permissions(manage_channels=True)
async def remove_user(interaction: discord.Interaction, user: discord.Member):
    data = tickets.get(interaction.channel.id)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    if user.id == data["opener"]:
        return await interaction.response.send_message("❌ Cannot remove the ticket opener.", ephemeral=True)
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"✅ {user.mention} has been removed from the ticket.")


@bot.tree.command(name="rename_ticket", description="Rename the current ticket channel")
@app_commands.describe(name="New channel name")
@app_commands.default_permissions(manage_channels=True)
async def rename_ticket(interaction: discord.Interaction, name: str):
    data = tickets.get(interaction.channel.id)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    await interaction.channel.edit(name=name)
    await interaction.response.send_message(f"✅ Ticket renamed to **{name}**.")


@bot.tree.command(name="ticket_stats", description="View ticket statistics")
@app_commands.default_permissions(manage_channels=True)
async def ticket_stats(interaction: discord.Interaction):
    total = len(tickets)
    claimed = sum(1 for t in tickets.values() if t["claimer"])
    unclaimed = total - claimed
    by_category = {}
    for t in tickets.values():
        by_category[t["category"]] = by_category.get(t["category"], 0) + 1

    embed = discord.Embed(title="📊 Ticket Statistics", color=discord.Color.blurple())
    embed.add_field(name="Open Tickets", value=str(total), inline=True)
    embed.add_field(name="Claimed", value=str(claimed), inline=True)
    embed.add_field(name="Unclaimed", value=str(unclaimed), inline=True)
    if by_category:
        cat_text = "\n".join(f"• {k}: {v}" for k, v in by_category.items())
        embed.add_field(name="By Category", value=cat_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="status", description="Change the status of the current ticket")
@app_commands.describe(status="Select ticket status: open, pending, or closed")
@app_commands.choices(
    status=[
        app_commands.Choice(name="Open", value="open"),
        app_commands.Choice(name="Pending", value="pending"),
        app_commands.Choice(name="Closed", value="closed"),
    ]
)
@app_commands.default_permissions(manage_channels=True)
async def ticket_status(interaction: discord.Interaction, status: str):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    
    if status not in ["open", "pending", "closed"]:
        return await interaction.response.send_message("❌ Invalid status. Use: open, pending, or closed.", ephemeral=True)
    
    old_status = data.get("status", "open")
    data["status"] = status
    data["last_activity"] = datetime.datetime.utcnow().isoformat()
    save_ticket_store()
    
    # Status emoji mapping
    status_emoji = {"open": "🟢", "pending": "🟡", "closed": "🔴"}
    status_colors = {
        "open": discord.Color.green(),
        "pending": discord.Color.orange(),
        "closed": discord.Color.red()
    }
    
    # Update channel name with status indicator
    channel = interaction.channel
    current_name = channel.name
    
    # Remove old status emoji if present
    emoji_list = list(status_emoji.values())
    for emoji in emoji_list:
        if current_name.startswith(emoji):
            current_name = current_name[2:].lstrip()
            break
    
    # Add new status emoji
    new_channel_name = f"{status_emoji[status]} {current_name}" if not current_name.startswith(tuple(emoji_list)) else f"{status_emoji[status]} {current_name}"
    
    try:
        await channel.edit(name=new_channel_name)
    except discord.Forbidden:
        pass  # Continue even if we can't rename
    
    # Create status update embed
    embed = discord.Embed(
        title="📝 Ticket Status Changed",
        description=f"Status changed from **{old_status.upper()}** to **{status.upper()}**",
        color=status_colors.get(status, discord.Color.blue()),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.add_field(name="Changed by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Timestamp", value=f"<t:{int(datetime.datetime.utcnow().timestamp())}:R>", inline=True)
    embed.add_field(name="Category", value=data.get("category", "Unknown"), inline=True)
    embed.add_field(name="Idle", value="✅ Yes" if data.get("idle") else "❌ No", inline=True)
    
    # Send status update in the channel
    await interaction.response.send_message(embed=embed)
    
    # Send DM to ticket opener notifying about status change
    if data.get("opener"):
        try:
            opener = await bot.fetch_user(data["opener"])
            user_embed = discord.Embed(
                title=f"{status_emoji[status]} Your Ticket Status Updated",
                description=f"Your ticket status in {interaction.guild.name} has been updated.",
                color=status_colors.get(status, discord.Color.blue()),
                timestamp=datetime.datetime.utcnow(),
            )
            user_embed.add_field(name="Previous Status", value=old_status.upper(), inline=True)
            user_embed.add_field(name="New Status", value=status.upper(), inline=True)
            user_embed.add_field(name="Category", value=data.get("category", "Unknown"), inline=False)
            user_embed.add_field(name="Updated by", value=interaction.user.mention, inline=False)
            user_embed.add_field(name="View Ticket", value=f"[Click here]({channel.jump_url})", inline=False)
            
            await opener.send(embed=user_embed)
        except (discord.NotFound, discord.Forbidden):
            pass  # Silently fail if DM can't be sent
    
    # If claimed, also notify the claimer
    if data.get("claimer"):
        try:
            claimer = await bot.fetch_user(data["claimer"])
            claimer_embed = discord.Embed(
                title=f"{status_emoji[status]} Ticket Status Update",
                description=f"A ticket you claimed has been updated.",
                color=status_colors.get(status, discord.Color.blue()),
                timestamp=datetime.datetime.utcnow(),
            )
            claimer_embed.add_field(name="Previous Status", value=old_status.upper(), inline=True)
            claimer_embed.add_field(name="New Status", value=status.upper(), inline=True)
            claimer_embed.add_field(name="Updated by", value=interaction.user.mention, inline=False)
            
            await claimer.send(embed=claimer_embed)
        except (discord.NotFound, discord.Forbidden):
            pass  # Silently fail if DM can't be sent


@bot.tree.command(name="idle", description="Mark the current ticket as inactive")
@app_commands.default_permissions(manage_channels=True)
async def mark_idle(interaction: discord.Interaction):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    
    data["idle"] = True
    data["last_activity"] = datetime.datetime.utcnow().isoformat()
    save_ticket_store()
    
    embed = discord.Embed(
        title="😴 Ticket Marked as Inactive",
        description="This ticket is now marked as idle and waiting for staff action.",
        color=discord.Color.greyple(),
    )
    embed.add_field(name="Marked by", value=interaction.user.mention, inline=False)
    embed.add_field(name="Time", value=f"<t:{int(datetime.datetime.utcnow().timestamp())}:R>", inline=False)
    embed.add_field(name="Tip", value="Use `/active` to revert this status.", inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="active", description="Mark the current idle ticket as active")
@app_commands.default_permissions(manage_channels=True)
async def mark_active(interaction: discord.Interaction):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    
    if not data.get("idle"):
        return await interaction.response.send_message(
            "ℹ️ This ticket is not marked as idle.",
            ephemeral=True
        )
    
    data["idle"] = False
    data["last_activity"] = datetime.datetime.utcnow().isoformat()
    save_ticket_store()
    
    embed = discord.Embed(
        title="✅ Ticket Marked as Active",
        description="This ticket is now marked as active and requires attention.",
        color=discord.Color.green(),
    )
    embed.add_field(name="Marked by", value=interaction.user.mention, inline=False)
    embed.add_field(name="Time", value=f"<t:{int(datetime.datetime.utcnow().timestamp())}:R>", inline=False)
    
    # Notify the ticket opener if available
    if data.get("opener"):
        try:
            opener = await bot.fetch_user(data["opener"])
            user_embed = discord.Embed(
                title="✅ Your Ticket is Now Active",
                description=f"Your ticket in {interaction.guild.name} has been marked as active again.",
                color=discord.Color.green(),
            )
            user_embed.add_field(name="Category", value=data["category"], inline=False)
            user_embed.add_field(name="Activated by", value=interaction.user.mention, inline=False)
            await opener.send(embed=user_embed)
        except (discord.NotFound, discord.Forbidden):
            pass
    
    await interaction.response.send_message(embed=embed)



@bot.tree.command(name="remind", description="Send a reminder about ticket inactivity to staff or user")
@app_commands.describe(target="Choose who to remind: staff or user")
@app_commands.choices(
    target=[
        app_commands.Choice(name="Staff", value="staff"),
        app_commands.Choice(name="User", value="user"),
    ]
)
@app_commands.default_permissions(manage_channels=True)
async def remind_ticket(interaction: discord.Interaction, target: str):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    
    channel = interaction.channel
    
    # Check if already reminded recently
    if channel.id in reminders:
        last_remind = datetime.datetime.fromisoformat(reminders[channel.id]["reminded_at"])
        if (datetime.datetime.utcnow() - last_remind).total_seconds() < 300:  # 5 minutes cooldown
            return await interaction.response.send_message(
                "⏰ This ticket was just reminded. Please wait 5 minutes before reminding again.",
                ephemeral=True
            )
    
    reminders[channel.id] = {
        "reminded_at": datetime.datetime.utcnow().isoformat(),
        "type": target
    }
    
    if target == "staff":
        # Send DM to staff members AND ping them in the ticket
        staff_members = []
        staff_mentions = []
        for member in interaction.guild.members:
            if member.guild_permissions.manage_channels and not member.bot:
                staff_members.append(member)
                staff_mentions.append(member.mention)
        
        # Send DM notifications to staff
        dm_embed = discord.Embed(
            title="🔔 Staff Reminder - Ticket Needs Attention",
            description=f"An inactive ticket has been flagged and requires your attention.",
            color=discord.Color.orange(),
        )
        dm_embed.add_field(name="Category", value=data['category'], inline=True)
        dm_embed.add_field(name="Opened by", value=f"<@{data['opener']}>", inline=True)
        dm_embed.add_field(name="Last Activity", value=f"<t:{int(datetime.datetime.fromisoformat(data['last_activity']).timestamp())}:R>", inline=False)
        dm_embed.add_field(name="Ticket Channel", value=f"[View in {interaction.guild.name}]({channel.jump_url})", inline=False)
        dm_embed.add_field(name="Reminder requested by", value=interaction.user.mention, inline=False)
        
        # DM each staff member
        dm_count = 0
        for staff_member in staff_members:
            try:
                await staff_member.send(embed=dm_embed)
                dm_count += 1
            except discord.Forbidden:
                pass
        
        # Ping staff in the ticket
        embed = discord.Embed(
            title="🔔 Staff Reminder",
            description="This ticket has been inactive and needs staff attention!",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Ticket", value=f"{data['category']} - Opened by <@{data['opener']}>", inline=False)
        embed.add_field(name="Last Activity", value=f"<t:{int(datetime.datetime.fromisoformat(data['last_activity']).timestamp())}:R>", inline=False)
        embed.add_field(name="Reminder sent by", value=interaction.user.mention, inline=False)
        
        message_content = " ".join(staff_mentions[:5]) if staff_mentions else "Staff"
        await channel.send(f"{message_content}", embed=embed)
        
        # Respond to the command user
        await interaction.response.send_message(
            f"✅ Reminder sent! DMs sent to {dm_count} staff member(s) and notification posted in channel.",
            ephemeral=True
        )
        
    else:  # user
        # Send DM to ticket opener
        if data.get("opener"):
            try:
                opener = await bot.fetch_user(data["opener"])
                embed = discord.Embed(
                    title="🔔 Ticket Reminder",
                    description=f"Your ticket in {interaction.guild.name} is awaiting your response.",
                    color=discord.Color.orange(),
                )
                embed.add_field(name="Category", value=data["category"], inline=False)
                embed.add_field(name="Channel", value=f"[View Ticket]({channel.jump_url})", inline=False)
                embed.add_field(name="Status", value=data.get("status", "open").upper(), inline=True)
                
                # Add note if ticket is idle
                if data.get("idle"):
                    embed.add_field(name="⚠️ Note", value="This ticket is currently marked as idle.", inline=False)
                
                await opener.send(embed=embed)
                
                # Also send notification in the ticket channel
                user_reminder_embed = discord.Embed(
                    title="📨 Reminder Sent to User",
                    description=f"A reminder has been sent to <@{data['opener']}>",
                    color=discord.Color.blue(),
                )
                user_reminder_embed.add_field(name="Sent by", value=interaction.user.mention, inline=False)
                await channel.send(embed=user_reminder_embed)
                
                await interaction.response.send_message(
                    f"✅ Reminder sent to <@{data['opener']}>",
                    ephemeral=True
                )
            except (discord.NotFound, discord.Forbidden):
                await interaction.response.send_message(
                    "❌ Could not send reminder to user. They may have DMs disabled.",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "❌ Could not find ticket opener.",
                ephemeral=True
            )


@bot.tree.command(name="auto-close", description="Set ticket to auto-close after specified time")
@app_commands.describe(
    time_value="Number of minutes or hours",
    unit="Time unit: minutes or hours"
)
@app_commands.choices(
    unit=[
        app_commands.Choice(name="Minutes", value="minutes"),
        app_commands.Choice(name="Hours", value="hours"),
    ]
)
@app_commands.default_permissions(manage_channels=True)
async def auto_close_ticket(interaction: discord.Interaction, time_value: int, unit: str):
    data = get_ticket_data(interaction.channel)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    
    if time_value <= 0:
        return await interaction.response.send_message("❌ Time value must be greater than 0.", ephemeral=True)
    
    # Convert to minutes
    multiplier = 60 if unit == "hours" else 1
    close_in_minutes = time_value * multiplier
    close_in_seconds = close_in_minutes * 60
    
    data["auto_close_time"] = int(datetime.datetime.utcnow().timestamp()) + close_in_seconds
    data["last_activity"] = datetime.datetime.utcnow().isoformat()
    save_ticket_store()
    
    embed = discord.Embed(
        title="⏱️ Auto-Close Scheduled",
        description=f"This ticket will automatically close in **{time_value} {unit}**",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Close Time", value=f"<t:{data['auto_close_time']}:R>", inline=False)
    embed.add_field(name="Set by", value=interaction.user.mention, inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="feedback", description="Rate your support experience")
async def give_feedback(interaction: discord.Interaction):
    # Check if user has any closed tickets
    if interaction.user.id not in ticket_history or not ticket_history[interaction.user.id]:
        await interaction.response.send_message(
            "ℹ️ You don't have any closed tickets to rate yet.",
            ephemeral=True
        )
        return
    
    await interaction.response.send_modal(FeedbackModal())


@bot.tree.command(name="history", description="View ticket history for a user")
@app_commands.describe(user="The user to view history for")
@app_commands.default_permissions(manage_channels=True)
async def view_history(interaction: discord.Interaction, user: discord.Member):
    if user.id not in ticket_history or not ticket_history[user.id]:
        return await interaction.response.send_message(
            f"ℹ️ {user.mention} has no ticket history.",
            ephemeral=True
        )
    
    history = ticket_history[user.id]
    embed = discord.Embed(
        title=f"📋 Ticket History for {user.name}",
        description=f"Total tickets: {len(history)}",
        color=discord.Color.blurple(),
    )
    
    for i, ticket in enumerate(history[-10:], 1):  # Show last 10 tickets
        status = ticket.get("status", "unknown")
        category = ticket.get("category", "Unknown")
        created = ticket.get("created_at", "Unknown")[:10]
        rating = ticket.get("feedback_rating", "N/A")
        
        field_value = f"**Category:** {category}\n**Created:** {created}\n**Status:** {status}\n**Rating:** {rating}"
        embed.add_field(name=f"Ticket #{ticket['ticket_id']}", value=field_value, inline=False)
    
    embed.set_footer(text=f"Requested by {interaction.user}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="blacklist", description="Blacklist a user from opening tickets and disable DM notifications")
@app_commands.describe(user="The user to blacklist", reason="Reason for blacklisting")
@app_commands.default_permissions(manage_channels=True)
async def blacklist_user(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if user.id in blacklist:
        await interaction.response.send_message(f"❌ {user.mention} is already blacklisted.", ephemeral=True)
        return
    
    blacklist[user.id] = {
        "blacklisted_by": interaction.user.id,
        "reason": reason,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    save_blacklist_store()
    
    embed = discord.Embed(
        title="🚫 User Blacklisted",
        description=f"{user.mention} has been blacklisted from opening tickets.",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Blacklisted By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"User ID: {user.id}")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unblacklist", description="Remove a user from the blacklist")
@app_commands.describe(user="The user to unblacklist")
@app_commands.default_permissions(manage_channels=True)
async def unblacklist_user(interaction: discord.Interaction, user: discord.Member):
    if user.id not in blacklist:
        await interaction.response.send_message(f"❌ {user.mention} is not blacklisted.", ephemeral=True)
        return
    
    del blacklist[user.id]
    save_blacklist_store()
    
    embed = discord.Embed(
        title="✅ User Unblacklisted",
        description=f"{user.mention} has been removed from the blacklist.",
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Unblacklisted By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"User ID: {user.id}")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="blacklist_list", description="View the blacklist")
@app_commands.default_permissions(manage_channels=True)
async def blacklist_list(interaction: discord.Interaction):
    if not blacklist:
        await interaction.response.send_message("📋 The blacklist is empty.", ephemeral=True)
        return
    
    embed = discord.Embed(title="🚫 Blacklist", color=discord.Color.red())
    
    for user_id, data in blacklist.items():
        blacklisted_by = f"<@{data['blacklisted_by']}>"
        timestamp = data['timestamp'][:10]  # Just the date
        embed.add_field(
            name=f"User ID: {user_id}",
            value=f"**Reason:** {data['reason']}\n**By:** {blacklisted_by}\n**Date:** {timestamp}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.event
async def on_ready():
    bot.add_view(TicketSetupView())
    bot.add_view(TicketControlView())
    auto_close_loop.start()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Failed to sync: {e}")
    print(f"🤖 {bot.user} is online!")


# ═══════════════════════════════════════════
#  BACKGROUND TASKS
# ═══════════════════════════════════════════

@tasks.loop(minutes=1)
async def auto_close_loop():
    """Check for tickets that need auto-closing"""
    current_time = int(datetime.datetime.utcnow().timestamp())
    
    for channel_id, data in list(tickets.items()):
        auto_close_time = data.get("auto_close_time")
        
        if auto_close_time and current_time >= auto_close_time:
            # Find the channel and close it
            guild = None
            for g in bot.guilds:
                channel = g.get_channel(channel_id)
                if channel:
                    guild = g
                    break
            
            if guild and channel:
                try:
                    # Create a pseudo-interaction to call close_ticket
                    class PseudoInteraction:
                        def __init__(self, ch, usr):
                            self.channel = ch
                            self.user = usr
                            self.guild = ch.guild
                            self.responded = False
                        
                        async def response_send_message(self, **kwargs):
                            await self.channel.send(**kwargs)
                        
                        @property
                        def response(self):
                            return self
                        
                        async def send_message(self, *args, **kwargs):
                            await self.channel.send(*args, **kwargs)
                        
                        async def followup_send(self, *args, **kwargs):
                            await self.channel.send(*args, **kwargs)
                        
                        @property
                        def followup(self):
                            return self
                    
                    bot_user = guild.get_member(bot.user.id)
                    pseudo = PseudoInteraction(channel, bot_user)
                    
                    # Send notification first
                    embed = discord.Embed(
                        title="⏰ Auto-Close Executed",
                        description="This ticket will be closed automatically.",
                        color=discord.Color.red(),
                    )
                    await channel.send(embed=embed)
                    
                    # Wait a moment then delete
                    await discord.utils.sleep_until(datetime.datetime.utcnow() + datetime.timedelta(seconds=3))
                    await channel.delete(reason="Auto-close timer completed")
                    tickets.pop(channel_id, None)
                    save_ticket_store()
                    
                except Exception as e:
                    print(f"Error auto-closing ticket {channel_id}: {e}")


# ═══════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════

if __name__ == "__main__":
    load_ticket_store()
    load_history_store()
    load_blacklist_store()
    if not TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: export DISCORD_BOT_TOKEN=your_token_here")
    else:
        bot.run(TOKEN)
