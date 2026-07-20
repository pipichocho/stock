import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
import yfinance as yf

TOKEN = "MTUyODU4NDI1MzQ4MTE2MDg0Ng.GfA811.dy_ISUd9j9SOO0QvHU3Ejc9EMquEvZu4zIP_EE"

# Trackers
# watched_stocks: { ticker_symbol: {"last_price": float, "channel_id": int, "user_id": int, "name": str} }
watched_stocks = {}

# target_alerts: list of dicts -> [{ "ticker": str, "target_price": float, "condition": "above" | "below", "channel_id": int, "user_id": int }]
target_alerts = []


# --- View Component ---
class MoreView(View):

    def __init__(self, ticker_symbol: str, stock_data: dict):
        super().__init__(timeout=None)
        self.ticker_symbol = ticker_symbol
        self.stock_data = stock_data

    @discord.ui.button(label="MORE", style=discord.ButtonStyle.primary)
    async def more(self, interaction: discord.Interaction, button: Button):
        button.disabled = True
        await interaction.message.edit(view=self)

        full_embed = discord.Embed(
            title=f"📊 {self.stock_data['name']} ({self.ticker_symbol.upper()})",
            color=0x00C853
            if self.stock_data["change_pct"] >= 0
            else 0xFF1744,
        )

        curr = self.stock_data["currency"]
        full_embed.add_field(
            name="💲 Price",
            value=f"{curr} {self.stock_data['price']:.2f}",
            inline=True,
        )
        full_embed.add_field(
            name="🎯 Target High",
            value=f"{curr} {self.stock_data['target_high']:.2f}",
            inline=True,
        )
        full_embed.add_field(
            name="📈 Day Change",
            value=f"{self.stock_data['change_pct']:+.2f}%",
            inline=True,
        )

        full_embed.add_field(
            name="📊 Market Stats",
            value=(
                f"• **52W High:** {curr} {self.stock_data['fifty_two_high']:.2f}\n"
                f"• **52W Low:** {curr} {self.stock_data['fifty_two_low']:.2f}\n"
                f"• **Volume:** {self.stock_data['volume']:,}\n"
                f"• **Market Cap:** {curr} {self.stock_data['market_cap']:,}"
            ),
            inline=False,
        )

        full_embed.set_footer(
            text=f"My Stock Bot • {datetime.now().strftime('%H:%M')}"
        )
        await interaction.response.send_message(
            embed=full_embed, ephemeral=False
        )


# --- Fetch Helper ---
def fetch_stock_info(symbol: str):
    symbol = symbol.strip().upper()
    tickers_to_try = (
        [f"{symbol}.TW", f"{symbol}.TWO", symbol] if symbol.isdigit() else [symbol]
    )

    for ticker_symbol in tickers_to_try:
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get(
                "regularMarketPreviousClose"
            )

            if price and prev_close:
                change_pct = ((price - prev_close) / prev_close) * 100
                currency = "NT$" if info.get("currency") == "TWD" else "$"

                return {
                    "symbol": ticker_symbol,
                    "name": info.get("shortName", symbol),
                    "price": price,
                    "target_high": info.get("targetHighPrice", 0.0),
                    "change_pct": change_pct,
                    "fifty_two_high": info.get("fiftyTwoWeekHigh", 0.0),
                    "fifty_two_low": info.get("fiftyTwoWeekLow", 0.0),
                    "volume": info.get("regularMarketVolume", 0),
                    "market_cap": info.get("marketCap", 0),
                    "currency": currency,
                }
        except Exception:
            continue
    return None

# --- Bot Setup ---
class StockBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Synced slash commands!")
        check_market_data.start()

bot = StockBot()

# --- Background Loop ---
@tasks.loop(seconds=60)
async def check_market_data():
    tickers_to_check = set(watched_stocks.keys()) | {
        alert["ticker"] for alert in target_alerts
    }

    for ticker in tickers_to_check:
        data = await asyncio.to_thread(fetch_stock_info, ticker)
        if not data:
            continue

        current_price = data["price"]
        curr = data["currency"]

        # 1. Process Target Alerts
        for alert in list(target_alerts):
            if alert["ticker"] == ticker:
                target_hit = False

                if alert["condition"] == "above" and current_price >= alert["target_price"]:
                    target_hit = True
                elif alert["condition"] == "below" and current_price <= alert["target_price"]:
                    target_hit = True

                if target_hit:
                    channel = bot.get_channel(alert["channel_id"])
                    if channel:
                        embed = discord.Embed(
                            title=f"🎯 TARGET REACHED: {data['name']} ({ticker})",
                            description=(
                                f"The stock reached your target price!\n\n"
                                f"• **Target Price:** {curr} {alert['target_price']:.2f}\n"
                                f"• **Current Price:** {curr} {current_price:.2f}\n"
                                f"• **Today's Change:** {data['change_pct']:+.2f}%"
                            ),
                            color=0x00C853
                            if data["change_pct"] >= 0
                            else 0xFF1744,
                        )
                        embed.set_footer(
                            text=f"My Stock Bot • {datetime.now().strftime('%H:%M')}"
                        )

                        view = MoreView(ticker, data)
                        await channel.send(
                            content=f"<@{alert['user_id']}>",
                            embed=embed,
                            view=view,
                        )

                    target_alerts.remove(alert)

        # 2. Process General Price Changes
        if ticker in watched_stocks:
            info = watched_stocks[ticker]
            old_price = info["last_price"]

            if current_price != old_price:
                price_diff = current_price - old_price
                direction = "🔺 UP" if price_diff > 0 else "🔻 DOWN"
                color = 0x00C853 if price_diff > 0 else 0xFF1744

                channel = bot.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        title=f"🚨 PRICE ALERT: {data['name']} ({ticker})",
                        description=(
                            f"Price moved **{direction}**!\n\n"
                            f"• **Old Price:** {curr} {old_price:.2f}\n"
                            f"• **New Price:** {curr} {current_price:.2f}\n"  # Fixed: changed new_price to current_price
                            f"• **Change:** {curr} {price_diff:+.2f} ({data['change_pct']:+.2f}% today)"
                        ),
                        color=color,
                    )
                    embed.set_footer(
                        text=f"My Stock Bot • {datetime.now().strftime('%H:%M')}"
                    )

                    view = MoreView(ticker, data)
                    await channel.send(
                        content=f"<@{info['user_id']}>", embed=embed, view=view
                    )

                watched_stocks[ticker]["last_price"] = current_price


@check_market_data.before_loop
async def before_check():
    await bot.wait_until_ready()


# --- Commands ---
@bot.tree.command(
    name="stock", description="Fetch live stock info for US or TW stocks."
)
@app_commands.describe(
    stock_number="Stock symbol or code (e.g. 0050, 2330, NVDA)"
)
async def stock(interaction: discord.Interaction, stock_number: str):
    await interaction.response.defer(thinking=True)
    data = await asyncio.to_thread(fetch_stock_info, stock_number)

    if not data:
        await interaction.followup.send(
            f"❌ Could not find stock data for `{stock_number}`."
        )
        return

    color = 0x00C853 if data["change_pct"] >= 0 else 0xFF1744
    curr = data["currency"]

    teaser_embed = discord.Embed(
        title=f"{data['name']} ({data['symbol']})",
        description=(
            f"💲 **Price:** {curr} {data['price']:.2f}\n"
            f"🎯 **Target:** {curr} {data['target_high']:.2f}\n"
            f"📈 **Change:** {data['change_pct']:+.2f}%\n"
            f"──────────────────────────"
        ),
        color=color,
    )
    teaser_embed.set_footer(
        text=f"My Stock Bot • {datetime.now().strftime('%H:%M')}"
    )

    view = MoreView(data["symbol"], data)
    await interaction.followup.send(embed=teaser_embed, view=view)


@bot.tree.command(
    name="watch",
    description="Toggle watch mode on a stock (adds or removes from watch list).",
)
@app_commands.describe(
    stock_number="Stock symbol or code (e.g. 0050, 2330, NVDA)"
)
async def watch(interaction: discord.Interaction, stock_number: str):
    await interaction.response.defer(thinking=True)
    data = await asyncio.to_thread(fetch_stock_info, stock_number)

    if not data:
        await interaction.followup.send(
            f"❌ Could not find stock data for `{stock_number}`."
        )
        return

    ticker = data["symbol"]
    curr = data["currency"]

    if ticker in watched_stocks:
        del watched_stocks[ticker]
        await interaction.followup.send(
            f"🔕 Stopped watching **{data['name']} ({ticker})**."
        )
    else:
        watched_stocks[ticker] = {
            "last_price": data["price"],
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "name": data["name"],
        }
        await interaction.followup.send(
            f"👀 Watching **{data['name']} ({ticker})**!\n"
            f"Current price: **{curr} {data['price']:.2f}**.\n"
            f"*(Run `/watch {stock_number}` again to unwatch)*"
        )


@bot.tree.command(
    name="target", description="Set a target price alert for a stock."
)
@app_commands.describe(
    code="Stock symbol or code (e.g. 0050, NVDA)",
    target="The target price to trigger an alert at (e.g. 100)",
)
async def target(interaction: discord.Interaction, code: str, target: float):
    await interaction.response.defer(thinking=True)
    data = await asyncio.to_thread(fetch_stock_info, code)

    if not data:
        await interaction.followup.send(
            f"❌ Could not find stock data for `{code}`."
        )
        return

    ticker = data["symbol"]
    curr = data["currency"]
    current_price = data["price"]

    condition = "above" if target >= current_price else "below"

    target_alerts.append(
        {
            "ticker": ticker,
            "target_price": target,
            "condition": condition,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
        }
    )

    direction_str = "rises to or above" if condition == "above" else "drops to or below"

    await interaction.followup.send(
        f"🎯 Target alert set for **{data['name']} ({ticker})**!\n"
        f"• **Current Price:** {curr} {current_price:.2f}\n"
        f"• **Target Price:** {curr} {target:.2f}\n\n"
        f"I will tag you when the price {direction_str} **{curr} {target:.2f}**."
    )


@bot.tree.command(
    name="list",
    description="List all currently watched stocks and active targets.",
)
async def list_alerts(interaction: discord.Interaction):
    embed = discord.Embed(title="📋 Active Stock Watchers & Targets", color=0x2B2D31)

    if watched_stocks:
        watch_text = "\n".join(
            [
                f"• **{info['name']} ({ticker})** — Last Price: `{info['last_price']:.2f}`"
                for ticker, info in watched_stocks.items()
            ]
        )
    else:
        watch_text = "None"

    if target_alerts:
        target_text = "\n".join(
            [
                f"• **{alert['ticker']}** — Target: `{alert['target_price']:.2f}`"
                for alert in target_alerts
            ]
        )
    else:
        target_text = "None"

    embed.add_field(name="👀 Watched Stocks", value=watch_text, inline=False)
    embed.add_field(name="🎯 Price Targets", value=target_text, inline=False)

    await interaction.response.send_message(embed=embed)


# --- Clear Command ---
@bot.tree.command(name="cls", description="Clears messages in the channel silently.")
@app_commands.describe(amount="Number of messages to delete (default: 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def cls(interaction: discord.Interaction, amount: int = 100):
    # Defer ephemerally so Discord acknowledges the command without posting a public message
    await interaction.response.defer(ephemeral=True)
    
    # Purge the messages
    await interaction.channel.purge(limit=amount)
    
    # Delete the hidden deferral acknowledgement silently
    await interaction.delete_original_response()


@cls.error
async def cls_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need 'Manage Messages' permission to use `/cls`.",
            ephemeral=True,
        )

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)