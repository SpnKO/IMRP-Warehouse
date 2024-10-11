import asyncio
import os
import json
import sqlite3
import time
import re
import pyotp
from datetime import datetime
import discord
from discord import app_commands
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Loading environment from .env and initiating a Chrome browser
load_dotenv()


class WHManagement(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.synced = False

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await tree.sync(guild=discord.Object(id=1131911351678287913))
            self.synced = True
        print(f'Logged in as {self.user.name}!')
        asyncio.ensure_future(logcollector())
        asyncio.ensure_future(calculator())
        # channel = client.get_channel(1224671070041145374)
        # startup = discord.Embed(title="Warehouse Management", description="Vincenzo Barzini, ready to load your "
        #                                                                   "warehouse with 1 million mats",
        #                        color=0x800080)
        # await channel.send(embed=startup)


client = WHManagement()
tree = app_commands.CommandTree(client)


async def logcollector():
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()

    async with async_playwright() as p:
        browser = await p.chromium.launch(slow_mo=2000)
        page = await browser.new_page()
        if os.path.isfile('./cookies.json'):
            with open("cookies.json", "r") as f:
                cookies = json.loads(f.read())
                await page.context.add_cookies(cookies)
        while True:
            await page.goto("https://sa-mp.im/profile/factionlogs?filter=TYPE_WH")
            if page.url == "https://sa-mp.im/login":
                await page.fill("input#username", os.getenv('IMRP_USERNAME'))
                await page.fill("input#password", os.getenv('IMRP_PASSWORD'))
                await page.click("input[type=submit]")
                await page.fill("input#otp", pyotp.TOTP(os.getenv('IMRP_OTP')).now())
                await page.click("input[type=submit]")
                await page.goto("https://sa-mp.im/profile/factionlogs?filter=TYPE_WH")
                with open("cookies.json", "w") as f:
                    f.write(json.dumps(await page.context.cookies()))

            table = page.locator("table")
            for row, row_index in zip(await table.locator("tr").all(), range(0, await table.locator("tr").count() - 2)):
                cell_one = None
                cell_three = None
                for cell, cell_index in zip(await row.locator("td").all(), range(0, 3)):
                    # print(f"Row {row_index}, Cell {cell_index} - Value: '{await cell.inner_text()}'")
                    if cell_index == 0:
                        cell_one = (
                            time.mktime(datetime.strptime(await cell.inner_text(), "%d.%m.%Y %H:%M").timetuple()))
                        if time.time() - cell_one <= 7200:
                            break
                    if cell_index == 2:
                        cell_three = await cell.inner_text()
                        if "has delivered" not in cell_three:
                            cell_one = None
                            cell_three = None
                            continue
                    if cell_one is not None and cell_three is not None:
                        cursor.execute('SELECT * FROM logs WHERE date = ? AND log = ?', (cell_one, cell_three))
                        if cursor.fetchone():
                            log_exists = True
                        else:
                            log_exists = False
                        if not log_exists:
                            cursor.execute("""INSERT INTO logs(date,log,accounted) VALUES (?,?,0)""",
                                           (cell_one, cell_three))
                            cell_one = None
                            cell_three = None
                            connection.commit()
            await asyncio.sleep(600)


async def calculator():
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    cursor2 = connection.cursor()
    while True:
        for row in cursor.execute('SELECT * from logs WHERE accounted = 0'):
            name = row[1].split(maxsplit=1)[0]
            amount = re.findall(r'\d+', row[1])
            if "metal" in row[1]:
                material = 'metal'
            else:
                material = 'lead'

            if material == 'metal':
                cursor2.execute("INSERT INTO payments(name, metal) VALUES (?,?) ON CONFLICT (name) DO UPDATE set "
                                "metal = metal + ? where name = ?", (name, amount[0], amount[0], name))
            else:
                cursor2.execute("INSERT INTO payments(name, lead) VALUES (?,?) ON CONFLICT (name) DO UPDATE set "
                                "lead = lead + ? where name = ?", (name, amount[0], amount[0], name))
            cursor2.execute("UPDATE logs SET accounted = 1 WHERE date = ? AND log = ?", (row[0], row[1]))
            connection.commit()
        await asyncio.sleep(600)


@tree.command(name="list", description="Lists all outstanding payments", guild=discord.Object(id=1131911351678287913))
async def self(interaction: discord.Interaction):
    """Lists all outstanding"""
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    result = ""
    for row in cursor.execute('SELECT * from payments ORDER BY name ASC'):
        if int(row[1]) >= int(row[2]):
            payment = row[2]
        else:
            payment = row[1]
        result = result + row[0] + " - " + ("{:,}".format(int(payment))) + "\n"
    await interaction.response.send_message(
        embed=discord.Embed(title="This is a list of outstanding payments:", description="**" + result + "**",
                            color=0x800080))


@tree.command(name="listtotal", description="List total materials", guild=discord.Object(id=1131911351678287913))
async def self(interaction: discord.Interaction):
    """Lists all outstanding"""
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    result = ""
    for row in cursor.execute('SELECT * from payments ORDER BY name ASC'):
        result = result + row[0] + " - metal:" + ("{:,}".format(int(row[1]))) + " - lead:" + (
            "{:,}".format(int(row[2]))) + "\n"
    await interaction.response.send_message(
        embed=discord.Embed(title="A list of all materials credited:", description="**" + result + "**",
                            color=0x800080))


@tree.command(name="clear", description="Clears a sum of materials from a player",
              guild=discord.Object(id=1131911351678287913))
async def clear(interaction: discord.Interaction, name: str, amount: int):
    """Clears a sum of materials from a player"""
    channel_id = interaction.channel_id
    if channel_id != 1224671109400756286:
        await interaction.response.send_message(
            embed=discord.Embed(title="You cannot execute this command in this channel", color=0x800080),
            ephemeral=True)
        return
    if amount < 0:
        await interaction.response.send_message(
            embed=discord.Embed(title="Invalid amount", color=0x800080), ephemeral=True)
        return
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM payments WHERE name = ?', (name,))
    data = cursor.fetchone()
    if data is None:
        await interaction.response.send_message(
            embed=discord.Embed(title="This name doesn't exist in the database", color=0x800080), ephemeral=True)
        return
    if data[1] < amount and data[2] < amount:
        await interaction.response.send_message(
            embed=discord.Embed(title="Invalid amount", color=0x800080), ephemeral=True)
        return

    cursor.execute('UPDATE payments SET metal = metal - ?, lead = lead - ? WHERE name = ?', (amount, amount, name))
    connection.commit()
    await interaction.response.send_message(
        embed=discord.Embed(title=str(amount) + " has been removed from " + name + " account", color=0x800080))


@tree.command(name="calcpay", description="Calculate the payout based on percentage",
              guild=discord.Object(id=1131911351678287913))
async def self(interaction: discord.Interaction, amount: int, percentage: int):
    channel_id = interaction.channel_id
    if channel_id != 1224671109400756286:
        await interaction.response.send_message(
            embed=discord.Embed(title="You cannot execute this command in this channel", color=0x800080),
            ephemeral=True)
        return
    if amount < 1:
        await interaction.response.send_message(
            embed=discord.Embed(title="Invalid amount", color=0x800080), ephemeral=True)
        return
    payout = amount * percentage / 100
    await interaction.response.send_message(
        embed=discord.Embed(title="The amount that needs to be paid is: " + str(payout) + " but clear " + str(amount),
                            color=0x800080))


@tree.command(name="getpay", description="Gets the amount that needs to be paid ",
              guild=discord.Object(id=1131911351678287913))
async def self(interaction: discord.Interaction, name: str, percentage: int):
    channel_id = interaction.channel_id
    if channel_id != 1224671109400756286:
        await interaction.response.send_message(
            embed=discord.Embed(title="You cannot execute this command in this channel", color=0x800080),
            ephemeral=True)
        return
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    result = ""
    for row in cursor.execute('SELECT * from payments'):
        if int(row[1]) >= int(row[2]):
            payment = row[2]
        else:
            payment = row[1]
        result = result + row[0] + " - " + str(payment) + "\n"
    await interaction.response.send_message(
        embed=discord.Embed(title="This is a list of outstanding payments:", description="**" + result + "**",
                            color=0x800080))


@tree.command(name="delete", description="Deletes someone from the database entirely",
              guild=discord.Object(id=1131911351678287913))
async def self(interaction: discord.Interaction, name: str):
    channel_id = interaction.channel_id
    if channel_id != 1224671109400756286:
        await interaction.response.send_message(
            embed=discord.Embed(title="You cannot execute this command in this channel", color=0x800080),
            ephemeral=True)
        return
    connection = sqlite3.connect(database="logs.db")
    cursor = connection.cursor()
    cursor.execute("DELETE FROM payments WHERE name = ?", (name,))
    data = cursor.fetchone()
    connection.commit()
    await interaction.response.send_message(
        embed=discord.Embed(title="Successfully removed " + name, color=0x800080))


client.run(os.getenv('DISCORD_TOKEN'))
