import discord
from discord.ext import commands
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
# ticket_channel_id -> { "opener": user_id, "claimer": user_id|None, "category": str, "answers": dict }
tickets = {}


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

    tickets[channel.id] = {
        "opener": user.id,
        "claimer": None,
        "category": category,
        "answers": answers,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

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
    await channel.send(
        "🤖 **Ticket Assistant Active**\n"
        "Your ticket is currently unclaimed. I can help you refine your request and gather more details while staff claims the ticket."
    )
    await interaction.response.send_message(
        f"✅ Your ticket has been created: {channel.mention}", ephemeral=True
    )


class AnnouncementChannelSelect(discord.ui.Select):
    def __init__(self, announcement: str, author_id: int, channels):
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
            title="📢 Announcement",
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
    def __init__(self, announcement: str, author_id: int, channels):
        super().__init__(timeout=120)
        self.add_item(AnnouncementChannelSelect(announcement, author_id, channels))


class AnnouncementModal(discord.ui.Modal, title="Create Announcement"):
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
        await interaction.response.send_message(
            "Select the channel you want to post the announcement in:",
            view=AnnouncementSelectView(announcement, interaction.user.id, channels),
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
        data = tickets.get(interaction.channel.id)
        if not data:
            return await interaction.response.send_message("❌ Ticket data not found.", ephemeral=True)
        if interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot close your own ticket.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        await close_ticket(interaction, reason=None)

    @discord.ui.button(label="🔒 Close With Reason", style=discord.ButtonStyle.danger, custom_id="ticket_close_reason")
    async def close_reason_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets.get(interaction.channel.id)
        if not data:
            return await interaction.response.send_message("❌ Ticket data not found.", ephemeral=True)
        if interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot close your own ticket.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        await interaction.response.send_modal(CloseReasonModal())

    @discord.ui.button(label="🙋 Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets.get(interaction.channel.id)
        if not data:
            return await interaction.response.send_message("❌ Ticket data not found.", ephemeral=True)
        if interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot claim your own ticket.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        if data["claimer"]:
            return await interaction.response.send_message(f"❌ Already claimed by <@{data['claimer']}>.", ephemeral=True)
        data["claimer"] = interaction.user.id
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
#  CLOSURE REQUEST (/closure_request)
# ═══════════════════════════════════════════

class ClosureRequestView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=None)
        self.requester_id = requester_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="closure_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets.get(interaction.channel.id)
        if not data:
            return
        if interaction.user.id == data["opener"]:
            return await interaction.response.send_message("❌ You cannot accept closure of your own ticket.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await close_ticket(interaction, reason="Closure request accepted")

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="closure_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets.get(interaction.channel.id)
        if not data:
            return
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
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

    # Generate transcript
    transcript_lines = []
    async for msg in channel.history(limit=500, oldest_first=True):
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        transcript_lines.append(f"[{timestamp}] {msg.author}: {msg.content}")
    transcript = "\n".join(transcript_lines)

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
        embed.add_field(name="Opened by", value=f"<@{data['opener']}>", inline=True)
        if data["claimer"]:
            embed.add_field(name="Claimed by", value=f"<@{data['claimer']}>", inline=True)

    # Send DM to ticket opener with full details
    if data:
        opener = interaction.guild.get_member(data["opener"])
        if opener:
            dm_embed = discord.Embed(
                title=f"🔒 Your {data['category']} Ticket Has Been Closed",
                description=f"Your ticket has been closed by {interaction.user.mention} in {interaction.guild.name}.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow(),
            )
            if reason:
                dm_embed.add_field(name="Reason for Closure", value=reason, inline=False)
            dm_embed.add_field(name="Closed At", value=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
            if data["claimer"]:
                dm_embed.add_field(name="Handled By", value=f"<@{data['claimer']}>", inline=True)
            
            # Add original answers
            dm_embed.add_field(name="Original Details", value="\n".join(f"**{q}:** {a}" for q, a in data["answers"].items()), inline=False)
            
            # Add transcript summary (first few messages)
            if transcript_lines:
                summary_lines = transcript_lines[:10]  # First 10 messages
                if len(transcript_lines) > 10:
                    summary_lines.append("... (truncated)")
                dm_embed.add_field(name="Conversation Summary", value="```\n" + "\n".join(summary_lines) + "\n```", inline=False)
            
            try:
                await opener.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # User has DMs disabled, silently ignore

    # Send transcript to log channel if configured
    if TRANSCRIPT_CHANNEL_ID:
        log_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
        if log_channel:
            file = discord.File(
                fp=io.BytesIO(transcript.encode()),
                filename=f"transcript-{channel.name}.txt",
            )
            await log_channel.send(embed=embed, file=file)

    # Send data to Kasi Vibes Studios data channel if applicable
    if interaction.guild.id == KASI_VIBES_GUILD_ID:
        data_channel = bot.get_channel(KASI_VIBES_DATA_CHANNEL_ID)
        if data_channel:
            file = discord.File(
                fp=io.BytesIO(transcript.encode()),
                filename=f"transcript-{channel.name}.txt",
            )
            await data_channel.send(embed=embed, file=file)

    await interaction.response.send_message(embed=embed)
    tickets.pop(channel.id, None)
    await discord.utils.sleep_until(datetime.datetime.utcnow() + datetime.timedelta(seconds=5))
    await channel.delete(reason=f"Ticket closed by {interaction.user}")


# ═══════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════

@bot.tree.command(name="announce", description="Create an announcement and pick the channel to post it in")
@app_commands.default_permissions(manage_guild=True)
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
    data = tickets.get(interaction.channel.id)
    if not data:
        return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
    if data["claimer"] != interaction.user.id and not interaction.user.guild_permissions.manage_channels:
        return await interaction.response.send_message("❌ Only the ticket claimer or staff can request closure.", ephemeral=True)

    embed = discord.Embed(
        title="🔒 Closure Request",
        description=f"{interaction.user.mention} is requesting to close this ticket.\nDo you accept?",
        color=discord.Color.orange(),
    )
    await interaction.response.send_message(embed=embed, view=ClosureRequestView(interaction.user.id))


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


def generate_ticket_assistant_response(message: discord.Message, data: dict):
    content = message.content.strip()
    if not content and not message.attachments:
        return None

    lower = content.lower()
    category = data["category"]
    if any(keyword in lower for keyword in ["status", "claim", "how long", "waiting", "when"]):
        return (
            "🤖 **Ticket Assistant:** This ticket is currently unclaimed. Staff should claim it soon. "
            "While you wait, please add any additional details or evidence you have."
        )

    if any(keyword in lower for keyword in ["thanks", "thank", "ty", "appreciate"]):
        return (
            "🤖 **Ticket Assistant:** You're welcome! If you'd like, I can help you summarize your issue "
            "for the staff member who claims this ticket."
        )

    if any(keyword in lower for keyword in ["report", "player", "rule", "cheat", "bug", "error", "issue", "problem", "help"]):
        if category == "Report Player":
            guidance = "Include the player name, the rule they broke, and any evidence you have."
        elif category == "Administrator":
            guidance = "Include your in-game name, the admin issue, and any relevant evidence or context."
        elif category == "In-Game Appeals":
            guidance = (
                "Include your in-game name, the punishment you received, and why you believe it should be lifted."
            )
        elif category == "Support":
            guidance = (
                "Include your in-game name, the exact issue, and any troubleshooting steps you've already tried."
            )
        else:
            guidance = "Describe your issue clearly and add any relevant details."
        return f"🤖 **Ticket Assistant:** {guidance} I will pass this information to staff when someone claims the ticket."

    return (
        "🤖 **Ticket Assistant:** I am here while your ticket is unclaimed. "
        "Please describe your issue clearly and include any relevant evidence or context so staff can help faster."
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    data = tickets.get(message.channel.id)
    if data and data["claimer"] is None and message.author.id == data["opener"]:
        response = generate_ticket_assistant_response(message, data)
        if response:
            await message.channel.send(response)

    await bot.process_commands(message)


# ═══════════════════════════════════════════
#  BOT EVENTS
# ═══════════════════════════════════════════

@bot.event
async def on_ready():
    bot.add_view(TicketSetupView())
    bot.add_view(TicketControlView())
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Failed to sync: {e}")
    print(f"🤖 {bot.user} is online!")


# ═══════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: export DISCORD_BOT_TOKEN=your_token_here")
    else:
        bot.run(TOKEN)
