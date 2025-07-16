import discord
from discord.ext import commands
from discord import app_commands


class Greet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.author.bot:
            if str.lower(message.content) == "hello":
                await message.channel.send("Hello")
            if str.lower(message.content) == "ez":
                await message.channel.send("woooo!!!!!")
        elif message.author != self.bot.user:
            if message.content == "睡什麼 起來嗨!!!!!!!":
                await message.channel.send("睡覺拉!!!")

    @app_commands.command(name="hello", description="Hello world")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message("Hello world!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Greet(bot))
