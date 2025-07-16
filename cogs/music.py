import discord
from discord.ext import tasks, commands
from discord import app_commands
from discord import FFmpegPCMAudio, PCMVolumeTransformer
import subprocess
import os
import shutil
from pytubefix import YouTube, Playlist
from pytubefix.cli import on_progress
from pytubefix.exceptions import VideoUnavailable, RegexMatchError
from collections import deque
import asyncio
import re
import time
from typing import Optional
import math
import logging
import atexit
import json


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.info = {}
        atexit.register(self.playlists_backup)
        self.remove_file.start()       

        self.video_regex = re.compile(
            r"(https?://)?(www\.)?((youtube\.com/watch\?v=)|(youtu\.be/)|(music\.youtube\.com/watch\?v=)).+"
        )
        self.playlist_regex = re.compile(
            r"(https?://)?(www\.)?((youtube\.com)|(youtu\.?be)|(music\.youtube\.com))/playlist\?list=.+"
        )
        for filename in os.listdir("downloads"):
            file_path = os.path.join("downloads", filename)
            shutil.rmtree(file_path)  # 删除文件夹及其所有内容

    def guild_info_init(self, guild_id):
        self.info[guild_id] = {
            "playlists": {"title": deque(), "id": deque()},
            "playing": {},
            "vote_info": {},
        }

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            self.guild_info_init(guild.id)
        if os.path.exists("play_lists.json"):
            with open("play_lists.json", "r") as file:
                loaded_playlists = json.load(file)
                for guild_id, data in loaded_playlists.items():
                    self.info[int(guild_id)]["playlists"] = {
                        "title": deque(data["title"]),
                        "id": deque(data["id"]),
                    }

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.guild_info_init(guild)

    def get_video_id(self, url):
        pattern = r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([^&]+)"
        match = re.search(pattern, url)
        if match is None:
            return None
        else:
            return match.group(1)

    def get_video_url(self, id):
        return f"https://www.youtube.com/watch?v={id}"

    async def add_playlists(self, url, mode, guild_id, index=0):
        def add(video, bias=0):
            id = self.get_video_id(video.watch_url)
            if mode == "appendleft":
                self.info[guild_id]["playlists"]["title"].insert(bias, video.title)
                self.info[guild_id]["playlists"]["id"].insert(bias, id)
                if bias == 0:
                    if (
                        "voice_client" in self.info[guild_id]
                        and (self.info[guild_id]["voice_client"].is_playing())
                        and self.info[guild_id]["playlists"]["title"][0]
                        != self.info[guild_id]["playing"]["title"]
                    ):
                        self.info[guild_id]["voice_client"].stop()
            elif mode == "append":
                self.info[guild_id]["playlists"]["title"].append(video.title)
                self.info[guild_id]["playlists"]["id"].append(id)
            elif mode == "insert":
                self.info[guild_id]["playlists"]["title"].insert(
                    index + bias, video.title
                )
                self.info[guild_id]["playlists"]["id"].insert(index + bias, id)

        def process_playlist():
            pl = Playlist(url)
            bias = 0
            for video in pl.videos:
                add(video, bias)
                bias += 1

        if self.playlist_regex.match(url):
            await asyncio.to_thread(process_playlist)

        elif self.video_regex.match(url):
            video = YouTube(url)
            add(video)

    def get_mean_volume(self, file_path): 
        
        result = subprocess.run(
            [
                "ffmpeg",
                "-i",
                file_path,
                "-af",
                "volumedetect",
                "-vn",
                "-sn",
                "-dn",
                "-f",
                "null",
                "NUL",
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=os.environ
        )
        output = result.stderr
        
        # Regex to find the mean volume from the output
        mean_match = re.search(r"mean_volume: ([\-\d\.]+) dB", output)
        if mean_match:
            mean_volume = float(mean_match.group(1))
            return mean_volume
        else:
            raise ValueError("Could not find volume levels in ffmpeg output")

    def play_audio(self, guild_id):
        filepath: str | None = None
        if not os.path.exists(f"downloads/{guild_id}"):
            os.makedirs(f"downloads/{guild_id}")
        try:
            yt = YouTube(
                self.get_video_url(self.info[guild_id]["playlists"]["id"][0]),
                on_progress_callback=on_progress,
            )
            ys = yt.streams.get_audio_only()
            if ys is None:
                print("Find youtube stream fail")
                return
            filepath = ys.download(f"downloads/{guild_id}")

        except Exception as e:
            print(e)

        self.info[guild_id]["playing"]["title"] = self.info[guild_id]["playlists"][
            "title"
        ][0]
        if filepath is None:
            print("Download video fail.")
            return
        try:
            self.info[guild_id]["playing"]["filename"] = os.path.basename(filepath)
            mean_volume = self.get_mean_volume(filepath)
            relative_volume = round(math.pow(10, (-16 - mean_volume) / 20), 2)
            source = FFmpegPCMAudio(source=filepath)
            audio_source = PCMVolumeTransformer(source, volume=relative_volume)
            self.info[guild_id]["voice_client"].play(
                audio_source, after=lambda e: self.after_playing(guild_id)
            )
        except Exception as e:
            print(e)

    def is_valid_youtube_url(self, url: str) -> bool:
        try:
            if self.video_regex.match(url) or self.playlist_regex.match(url):
                return True
            else:
                return False
        except (VideoUnavailable, RegexMatchError):
            return False

    @app_commands.command(
        name="play", description="將機器人加入頻道並插入播放音樂(插入單曲或播放清單)"
    )
    @app_commands.describe(url="可以加入歌曲或播放清單")
    async def play(self, interaction: discord.Interaction, url: Optional[str] = None):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        if (
            isinstance(interaction.user, discord.Member)
            and interaction.user.voice is not None
        ):
            channel = interaction.user.voice.channel
            if channel is None:
                await interaction.response.send_message("無法取得語音頻道")
                return
            if url is not None:
                if self.is_valid_youtube_url(url):
                    await interaction.response.send_message(f"播放音樂\n{url}")
                    asyncio.create_task(self.add_playlists(url, "appendleft", guild_id))
                else:
                    await interaction.response.send_message("無效輸入")
                    return
            else:
                if "voice_client" in self.info[guild_id] and (
                    self.info[guild_id]["voice_client"].is_playing()
                ):
                    await interaction.response.send_message(
                        f"已播放音樂\n[{self.info[guild_id]['playlists']['title'][0]}]({self.get_video_url(self.info[guild_id]['playlists']['id'][0])})"
                    )
                    return
                elif len(self.info[guild_id]["playlists"]["title"]) > 0:
                    await interaction.response.send_message(
                        f"播放音樂\n[{self.info[guild_id]['playlists']['title'][0]}]({self.get_video_url(self.info[guild_id]['playlists']['id'][0])})"
                    )
                else:
                    await interaction.response.send_message("播放清單中沒有音樂")
                    return
            if interaction.guild.voice_client:
                voice = interaction.guild.voice_client
                if (
                    isinstance(voice, discord.voice_client.VoiceClient)
                    and voice != self.info[guild_id]["voice_client"]
                ):
                    await voice.move_to(channel)
            else:
                self.info[guild_id]["voice_client"] = await channel.connect()

            self.play_audio(guild_id)
        else:
            await interaction.response.send_message("你尚未連接到任何語音頻道")

    @app_commands.command(name="leave", description="離開語音頻道(會保留播放清單)")
    async def leave(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        if (
            self.info[guild_id]["voice_client"]
            and self.info[guild_id]["voice_client"].is_connected()
        ):
            await interaction.response.send_message("機器人已離開語音頻道QwQ")
            await self.info[guild_id]["voice_client"].disconnect()
        else:
            await interaction.response.send_message("機器人尚未連接到任何語音頻道")

    @app_commands.command(name="skip", description="跳過當前音樂")
    async def skip(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        await interaction.response.send_message(
            f"已跳過音樂\n{self.info[guild_id]['playlists']['title'][0]}"
        )
        if "voice_client" in self.info[guild_id] and (
            self.info[guild_id]["voice_client"].is_playing()
        ):
            self.info[guild_id]["voice_client"].stop()
        else:
            self.info[guild_id]["playlists"]["title"].popleft()
            self.info[guild_id]["playlists"]["id"].popleft()

    @app_commands.command(name="add", description="將youtube音樂(播放清單)加入播放清單")
    @app_commands.describe(url="可以加入歌曲或播放清單", index="從第幾首歌後開始加")
    async def add(
        self, interaction: discord.Interaction, url: str, index: Optional[int] = None
    ):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        if index is None:
            if self.is_valid_youtube_url(url):
                await interaction.response.send_message(f"加入音樂\n{url}")
                await self.add_playlists(url, "append", guild_id)
            else:
                await interaction.response.send_message("無效輸入")
        else:
            if index >= 1 and index <= len(self.info[guild_id]["playlists"]["title"]):
                if self.is_valid_youtube_url(url):
                    await interaction.response.send_message(f"加入音樂\n{url}")
                    await self.add_playlists(url, "insert", guild_id, index)
                else:
                    await interaction.response.send_message("無效輸入")
            else:
                await interaction.response.send_message("無效輸入")

    @app_commands.command(name="remove", description="清除播放清單")
    async def remove(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        if len(self.info["playlists"]["title"]) == 0:
            await interaction.response.send_message("播放清單為空")
        else:
            self.info[guild_id]["playlists"]["title"].clear()
            self.info[guild_id]["playlists"]["id"].clear()
            await interaction.response.send_message("清除全部播放清單")
            if (
                "voice_client" in self.info[guild_id]
                and self.info[guild_id]["voice_clent"].is_connected()
            ):
                await self.info[guild_id]["voice_clent"].disconnect()

    @app_commands.command(name="list", description="顯示播放清單")
    async def list(self, interaction: discord.Interaction, page: Optional[int] = 1):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        embed = discord.Embed(
            title="播放清單",
            description=f"第 {page} 頁(共{math.ceil(len(self.info[guild_id]['playlists']['title']) / 10)}頁)",
            color=0x0000FF,
        )
        if page is None:
            return
        for a in range((page - 1) * 10, page * 10):
            if a < len(self.info[guild_id]["playlists"]["title"]):
                if (
                    a == 0
                    and "voice_client" in self.info[guild_id]
                    and (self.info[guild_id]["voice_client"].is_playing())
                ):
                    embed.add_field(
                        name="",
                        value=f"{a + 1}. [{self.info[guild_id]['playlists']['title'][a]}]({self.get_video_url(self.info[guild_id]['playlists']['id'][a])})    (正在播放)",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="",
                        value=f"{a + 1}. [{self.info[guild_id]['playlists']['title'][a]}]({self.get_video_url(self.info[guild_id]['playlists']['id'][a])})",
                        inline=False,
                    )
            else:
                break
        await interaction.response.send_message(embed=embed)

    def after_playing(self, guild_id):
        async def disconnect():
            await self.info[guild_id]["voice_client"].disconnect()

        if self.info[guild_id]["playlists"]["title"][0] == self.info[guild_id][
            "playing"
        ]["title"] and not (self.info[guild_id]["voice_client"].is_playing()):
            self.info[guild_id]["playlists"]["title"].popleft()
            self.info[guild_id]["playlists"]["id"].popleft()
        if len(self.info[guild_id]["playlists"]["title"]) > 0:
            self.play_audio(guild_id)
        else:
            asyncio.run_coroutine_threadsafe(disconnect(), self.bot.loop)

    @tasks.loop(minutes=3)
    async def remove_file(self):
        for guild_id in self.info:
            for filename in os.listdir(f"downloads/{guild_id}"):
                if filename not in self.info[guild_id]["playing"]["filename"]:
                    try:
                        file_path = os.path.join(f"downloads/{guild_id}", filename)
                        os.remove(file_path)
                    except Exception as e:
                        logging.basicConfig(level=logging.ERROR)
                        logger = logging.getLogger(__name__)
                        logger.error(e)

    @app_commands.command(
        name="vote_skip",
        description="發起後20秒內音樂頻道有超過1/4使用者同意且同意人數大於反對人數就跳過音樂",
    )
    async def vote_skip(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        self.start_time = time.time()

        user = interaction.user
        if user is None or not isinstance(user, discord.Member):
            return
        voice = user.voice
        if voice is None:
            return
        voice_channel = voice.channel
        if voice_channel is None:
            return
        members = voice_channel.members
        if members is None:
            return

        self.info[guild_id]["vote_info"] = {
            "members": len(members),
            "voted_id": [],
            "vote": 0,
            "agree": 0,
            "disagree": 0,
        }
        if self.info[guild_id]["voice_client"] and (
            self.info[guild_id]["voice_client"].is_playing()
        ):
            view = discord.ui.View()
            agree_button = discord.ui.Button(
                label="同意跳過", style=discord.ButtonStyle.blurple
            )
            agree_button.callback = lambda interaction: self.vote_callback(
                interaction, guild_id, "agree"
            )
            disagree_button = discord.ui.Button(
                label="不同意跳過", style=discord.ButtonStyle.blurple
            )
            disagree_button.callback = lambda interaction: self.vote_callback(
                interaction, guild_id, "disagree"
            )
            view.add_item(agree_button)
            view.add_item(disagree_button)
            await interaction.response.send_message(view=view)
            self.bot.loop.create_task(self.vote_end(interaction, guild_id))
        else:
            await interaction.response.send_message("無任何音樂正在播放")

    async def vote_callback(
        self, interaction: discord.Interaction, guild_id: int, vote_type: str
    ):
        await interaction.response.send_message(
            f"等待中！還有{int(20 - (time.time() - self.start_time))}秒", ephemeral=True
        )
        vote_info = self.info[guild_id]["vote_info"]
        user = interaction.user
        if user is None or not isinstance(user, discord.Member):
            return
        voice = user.voice
        if voice is None:
            return
        voice_channel = voice.channel
        if voice_channel is None:
            return
        members = voice_channel.members
        if members is None:
            return
        if (
            interaction.user.id not in vote_info["voted_id"]
            and interaction.user in members
        ):
            vote_info["voted_id"].append(interaction.user.id)
            vote_info["vote"] += 1
            if vote_type == "agree":
                vote_info["agree"] += 1
            elif vote_type == "disagree":
                vote_info["disagree"] += 1

    async def vote_end(self, interaction: discord.Interaction, guild_id: int):
        await asyncio.sleep(20)
        vote_info = self.info[guild_id]["vote_info"]
        if not isinstance(interaction.channel, discord.abc.Messageable):
            return
        await interaction.channel.send(
            f"{vote_info['vote']}人投票 {vote_info['agree']}人同意跳過 {vote_info['disagree']}人不同意跳過"
        )
        if vote_info["vote"] / vote_info["members"] >= 0.25:
            if vote_info["agree"] > vote_info["disagree"]:
                await interaction.channel.send("跳過此首")
                if len(self.info[guild_id]["playlists"]) > 0:
                    await interaction.channel.send(
                        f"已跳過音樂{self.get_video_url(self.info[guild_id]['playlists']['id'][0])}"
                    )
                    self.info[guild_id]["voice_client"].stop()
                    return
                else:
                    await interaction.channel.send("播放清單已無音樂")
        await interaction.channel.send("繼續收聽")

    def playlists_backup(self):
        playlists_converted = {
            guild_id: {
                "title": list(data["playlists"]["title"]),
                "id": list(data["playlists"]["id"]),
            }
            for guild_id, data in self.info.items()
        }
        print(playlists_converted)
        with open("play_lists.json", "w") as file:
            json.dump(playlists_converted, file, indent=4)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
