import json
import os
import atexit
import discord
from discord.ext import tasks, commands
from discord import app_commands
import datetime as dt
from datetime import datetime
import math
import re
from typing import Optional
from functools import wraps


def user_id_exists(func):
    @wraps(func)
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
        user_id = interaction.user.id
        if user_id in self.remind_data:
            return await func(self, interaction, *args, **kwargs)
        else:
            await interaction.response.send_message("請先設定提醒頻道", ephemeral=True)

    return wrapper


class Remind(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.everyday.start()
        self.remind_data = {}
        if os.path.exists("remind_data.json"):
            with open("remind_data.json", "r") as file:
                loaded_remind_data = json.load(file)
                self.remind_data = {
                    int(key): value for key, value in loaded_remind_data.items()
                }

        atexit.register(self.backup_remind_lists)
        self.date_regex = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")

    @app_commands.command(name="remind_channel", description="設定提醒頻道")
    async def remind_channel(self, interaction: discord.Interaction):
        if interaction.channel is None:
            return

        user_id = interaction.user.id
        if user_id not in self.remind_data:
            self.remind_data[user_id] = {
                "remind_channel": interaction.channel.id,
                "lists": [],
            }
        else:
            self.remind_data[user_id]["remind_channel"] = interaction.channel.id
        await interaction.response.send_message(
            "將此頻道設為預設提醒頻道", ephemeral=True
        )

    def is_valid_date(self, date_str: str) -> bool:
        date_format = "%Y/%m/%d"
        try:
            datetime.strptime(date_str, date_format)
            return True
        except ValueError:
            return False

    @app_commands.command(name="add_remind", description="增加提醒項目")
    @app_commands.describe(
        first_date="第一次提醒日期",
        title="標題",
        content="詳細內容",
        times_limit="提醒次數(預設無限次))",
        cycles="週期(單位是天,預設每天)",
    )
    @user_id_exists
    async def add_remind(
        self,
        interaction: discord.Interaction,
        first_date: str,
        title: str,
        content: Optional[str] = None,
        times_limit: Optional[int] = None,
        cycles: Optional[int] = 1,
    ):
        if (
            self.date_regex.match(first_date)
            and (times_limit is None or times_limit > 0)
            and (cycles is not None)
            and self.is_valid_date(first_date)
        ):
            user_id = interaction.user.id
            added_remind = {
                "title": title,
                "content": content,
                "first_date": first_date,
                "cycles": cycles,
                "times_limit": times_limit,
                "times": 0,
            }
            self.remind_data[user_id]["lists"].append(added_remind)
            await interaction.response.send_message("已新增項目", ephemeral=True)
        else:
            await interaction.response.send_message("無效的參數", ephemeral=True)

    @app_commands.command(name="remove_remind", description="移除提醒項目")
    @app_commands.describe(index="編號")
    @user_id_exists
    async def remove_remind(self, interaction: discord.Interaction, index: int):
        user_id = interaction.user.id
        if index > 0 and index <= len(self.remind_data[user_id]["lists"]):
            self.remind_data[user_id]["lists"].pop(index - 1)
            await interaction.response.send_message("已移除項目", ephemeral=True)
        else:
            await interaction.response.send_message("無效的參數", ephemeral=True)

    @app_commands.command(name="remind_list", description="顯示提醒項目")
    @user_id_exists
    async def remind_list(
        self, interaction: discord.Interaction, page: Optional[int] = 1
    ):
        user_id = interaction.user.id
        embed = discord.Embed(
            title="提醒項目",
            description=f"第 {page} 頁(共{math.ceil(len(self.remind_data[user_id]['lists']) / 10)}頁)",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        if page is None:
            return
        for a in range((page - 1) * 10, page * 10):
            if a < len(self.remind_data[user_id]["lists"]):
                remind = self.remind_data[user_id]["lists"][a]
                if remind["times_limit"] is None:
                    embed.add_field(
                        name=f"{a + 1}. {remind['title']}",
                        value=f"{remind['content']}({remind['times']}/∞)\n首次提醒於{remind['first_date']}  提醒間隔{remind['cycles']}天",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name=f"{a + 1}. {remind['title']}",
                        value=f"{remind['content']}({remind['times']}/{remind['times_limit']})\n首次提醒於{remind['first_date']}  提醒間隔{remind['cycles']}天",
                        inline=False,
                    )
            else:
                break
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def days_apart(self, date) -> int:
        date_format = "%Y/%m/%d"
        date1 = datetime.strptime(date, date_format).date()
        date2 = datetime.strptime(
            datetime.now().strftime("%Y/%m/%d"), "%Y/%m/%d"
        ).date()
        delta = abs((date2 - date1).days)
        return delta

    @tasks.loop(
        time=dt.time(hour=6, minute=0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    )
    async def everyday(self):
        for user_id in self.remind_data:
            user = await self.bot.fetch_user(user_id)
            remind_lists = []
            for a in range(len(self.remind_data[user_id]["lists"])):
                remind = self.remind_data[user_id]["lists"][a]
                self.days_apart(remind["first_date"])
                if self.days_apart(remind["first_date"]) % remind["cycles"] == 0:
                    remind_lists.append(remind)
                    remind["times"] += 1
                    if remind["times_limit"]:
                        if remind["times"] == remind["times_limit"]:
                            self.remind_data[user_id]["lists"].pop(a)
            if len(remind_lists) > 0:
                channel = self.bot.get_channel(
                    self.remind_data[user_id]["remind_channel"]
                )
                if not isinstance(channel, discord.abc.Messageable):
                    return

                await channel.send(user.mention)
                embed = discord.Embed(
                    title="提醒項目",
                    color=discord.Color.green(),
                    timestamp=datetime.now(),
                )
                for a in range(len(remind_lists)):
                    embed.add_field(
                        name=f"{a + 1}. {remind_lists[a]['title']}",
                        value=f"{remind_lists[a]['content']}",
                        inline=False,
                    )
                await channel.send(embed=embed)

    def backup_remind_lists(self):
        with open("remind_data.json", "w") as file:
            json.dump(self.remind_data, file)


async def setup(bot: commands.Bot):
    await bot.add_cog(Remind(bot))
