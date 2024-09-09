# This project is licensed under the terms of the GPL v3.0 license. Copyright 2024 Cyteon
from random import random
import discord
import requests
import os

import re

import time
import asyncio
import functools
import http.client
import aiohttp
import base64
import aiohttp
import random
import logging
import json

from io import BytesIO
from datetime import datetime

from groq import Groq

from discord import app_commands, Webhook
from discord.ext import commands, tasks
from discord.ext.commands import Context
from utils import CONSTANTS, DBClient, CachedDB

client = DBClient.client
db = client.sentient

logger = logging.getLogger("discord_bot")

if not os.path.isfile(f"./config.json"):
    sys.exit("'config.json' not found! Please add it and try again.")
else:
    with open(f"./config.json") as file:
        config = json.load(file)

models = [
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "llama3-groq-70b-8192-tool-use-preview",
    "llama3-groq-8b-8192-tool-use-preview",
    "gemma2-9b-it"
]

ai_temp_disabled = False

ai_channels = []
c = db["ai_channels"]
data = c.find_one({ "listOfChannels": True })
logger.info("Initing AI channels")

if data:
    ai_channels = data["ai_channels"]
    logger.info("AI Channels data Found")
else:
    logger.info("Creating AI Channels data")
    data = {
    	"listOfChannels": True,
         "ai_channels": []
    }
    c.insert_one(data)

last_api_key = 1
total_api_keys = os.getenv("GROQ_API_KEY_COUNT")

def get_api_key():
    global last_api_key
    global total_api_keys

    if str(last_api_key) == total_api_keys:
        last_api_key = 1
    else:
        last_api_key += 1

    return os.getenv("GROQ_API_KEY_" + str(last_api_key))

systemPrompt="""
You are the user with the id 1268929435457818717.
If someone talks to someone else dont always say stuff, dont always use reply for a message, sometimes have reply_or_send to false.
Respond in JSON only, you are a discord user, and need to act like one, if you dont wanna respond set skip to true,
The delay between each message is 1sec
here is how to respond (reply_or_send will make first message a reply if true, just send msg if false, if you get a message that says 'random' then just come up with something discord user like to say):
you have to set action no matter what, always use unicode, convert discord emojis like :gift: to unicode always
{'skip': bool, 'messages': [str], 'reply_or_send': bool, 'action': str, 'reactions': [emoji (unicode)]}
for just one message do messages: [your one message]
do array of emojis
Avaible actions: message, react
"""
def prompt_ai(
        prompt="Hello",
        channelId = 0,
        userInfo="",
        groq_client=Groq(api_key=get_api_key()),
        systemPrompt=systemPrompt
    ):
    c = db["ai_convos"]
    data = {}

    messageArray = []

    if channelId != 0:
        data = CachedDB.sync_find_one(c, { "isChannel": True, "id": channelId })

        if data:
            messageArray = data["messageArray"]
        else:
            data = { "isChannel": True, "id": channelId, "messageArray": [] }

            c.insert_one(data)

    messageArray.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    newMessageArray = messageArray.copy()

    newMessageArray.append(
    	{
            "role": "system",
            "content": f"{systemPrompt} | UserInfo: {userInfo}"
        }
    )

    ai_response = ""

    for model in models:
        try:
            ai_response = groq_client.chat.completions.create(
                messages=newMessageArray,
                model=model,
                response_format={"type": "json_object"},
                max_tokens=100,
            ).choices[0].message.content

            break
        except Exception as e:
            ai_response = f"Error: {e}"

    messageArray.append(
        {
            "role": "assistant",
            "content": ai_response
        }
    )

    if len(messageArray) >= 24 :
        newdata = {
                "$set": { "messageArray": messageArray[2::],  }
        }
    else:
        newdata = {
                "$set": { "messageArray": messageArray  }
        }

    if channelId != 0:
        CachedDB.sync_update_one(
            c, { "isChannel": True, "id": channelId}, newdata
        )

    ai_response = ai_response.replace("</s>", " ") # It kept sending this somtimes

    return ai_response


class Ai(commands.Cog, name="🤖 AI"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.ai_temp_disabled = False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.bot or message.author.bot:
            return

        if self.ai_temp_disabled:
            return

        if message.content.startswith("??") or message.content.startswith("-"):
            return

        if not self.bot.user in message.mentions:
            if message.guild:
                if not message.channel.id in ai_channels:
                    return

        client = Groq(api_key=get_api_key())

        c = db["users"]
        userInfo = await CachedDB.find_one(c, {"id": message.author.id, "guild_id": message.guild.id})

        if not userInfo:
            userInfo = {}

        userInfo["user"] = message.author
        userInfo["channel"] = message.channel


        loop = asyncio.get_running_loop()
        try:
            data_str = await loop.run_in_executor(None, functools.partial(prompt_ai, message.author.name + ": " + message.content, message.channel.id, str(userInfo), groq_client=client, systemPrompt=systemPrompt))

            data = json.loads(data_str)

            logger.info(data)

            if "message" in data: # AI is stupid sometimes
                data["messages"] = [data["message"]]

            if "reaction" in data: # AI is stupid sometimes
                if type(data["reaction"]) == list:
                    data["reactions"] = data["reaction"]
                else:
                    data["reactions"] = [data["reaction"]]

            if data["skip"]:
                return

            if not "action" in data:
                return

            if data["action"] == "message" and data["messages"] != []:
                i = 0
                for msg in data["messages"]:
                    async with message.channel.typing():
                        if i == 0:
                            if "reply_or_send" in data:
                                if data["reply_or_send"]:
                                    await message.reply(msg)
                                else:
                                    await message.channel.send(msg)
                            else:
                                await message.channel.send(msg)
                        else:
                            await message.channel.send(msg)
                            await asyncio.sleep(1)

                        i += 1

                logger.info(f"AI replied to {message.author} in {message.guild.name} ({message.guild.id})")

            if "reactions" in data:
                data["reactions"] = data["reactions"][0:3]
                for reaction in data["reactions"]:
                    try:
                        await message.add_reaction(reaction)
                    except:
                        pass

        except Exception as e:
            err = f"An error in the AI has occured {e}"
            await message.reply(err)

    @commands.command(
        name="toggle-ai",
        description="Reset AI data (owner only)",
    )
    @commands.is_owner()
    async def toggle_ai(self, context: Context) -> None:
        self.ai_temp_disabled = not self.ai_temp_disabled

        if self.ai_temp_disabled:
            await context.send("AI is now disabled globally")
        else:
            await context.send("AI is now enabled globally")

    @commands.command(
        name="enable",
        description="Enable AI in this channel",
    )
    @commands.has_permissions(manage_messages=True)
    async def enable(self, context: Context) -> None:
        c = db["ai_channels"]

        if context.channel.id in ai_channels:
            await context.send("AI is already enabled in this channel")
            return

        ai_channels.append(context.channel.id)

        c.update_one({ "listOfChannels": True }, { "$set": { "channels": ai_channels } }, upsert=True)

        await context.send("AI has been enabled in this channel")

    @commands.command(
        name="disable",
        description="Disable AI in this channel",
    )
    @commands.has_permissions(manage_messages=True)
    async def disable(self, context: Context) -> None:
        c = db["ai_channels"]

        if not context.channel.id in ai_channels:
            await context.send("AI is already disabled in this channel")
            return

        ai_channels.remove(context.channel.id)

        c.update_one({ "listOfChannels": True }, { "$set": { "channels": ai_channels } }, upsert=True)

        await context.send("AI has been disabled in this channel")

    @commands.hybrid_command(
        name="reset",
        description="Reset AI",
    )
    async def reset(self, context: Context) -> None:
        c = db["ai_convos"]

        c.delete_one({ "isChannel": True, "id": context.channel.id })

        await context.send("AI has been reset in this channel")

async def setup(bot) -> None:
    await bot.add_cog(Ai(bot))
