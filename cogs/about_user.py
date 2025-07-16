import discord
from discord.ext import commands
from discord import app_commands
from discord.app_commands import Choice


class About(commands.Cog):
    def __intit__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="introduce", description="玩家介紹")
    @app_commands.describe(name="想看誰的介紹")
    @app_commands.choices(
        name=[
            Choice(name="Ant", value="Ant"),
            Choice(name="80", value="80"),
        ]
    )
    async def about(self, interaction: discord.Interaction, name: Choice[str]):
        if name.value == "Ant":
            await interaction.response.send_message("普通的螞蟻 但我不是螞蟻")
        if name.value == "80":
            await interaction.response.send_message("價值遠超80?")


async def setup(bot: commands.Bot):
    await bot.add_cog(About(bot))
