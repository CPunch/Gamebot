'''
    gamebot.py
        Discord bot to let a discord server play gameboy games together. Put discord bot token into 'token.txt'

    Requires:
        - PILlow
        - Discord.py
        - PyBoy

    Author: CPunch
'''
import io
import os
from pyboy import PyBoy, WindowEvent
from PIL import Image
import discord
import asyncio
from discord.ext import commands, tasks
from discord.ext.commands import Bot
from discord.ext.tasks import loop

ROMS = { # rom, default save, frames per request
# ================[[ POKEMON ]]================
    "pkm_red":("roms/red.gb", "roms/red.sv", 120),
    "pkm_blue":("roms/blue.gb", "roms/blue.sv", 120),
    "pkm_yellow":("roms/yellow.gbc", "roms/yellow.sv", 120), # for nerds

    "pkm_silver":("roms/silver.gbc", "roms/silver.sv", 120),
    "pkm_gold":("roms/gold.gbc", "roms/gold.sv", 120),

# ================[[ DRAGON QUEST ]]================
    "dragon_quest":("roms/quest.gbc", "roms/quest.sv", 120),

# ================[[ TETRIS ]]================
    "tetris":("roms/tetris.gb", "roms/tetris.sv", 60),

# ================[[ FROGGER ]]================
    "frogger":("roms/frogger.gbc", "roms/frogger.sv", 60),

# ================[[ Harvest Moon ]]================
    "harvest_moon":("roms/harvest2.gbc", "roms/harvest2.sv", 150),

# ================[[ Dr Mario ]]================
    "dr_mario":("roms/dr_mario.gb", "roms/dr_mario.sv", 60),
}

# generates the save state
for key in ROMS:
    rom = ROMS[key]
    print(rom[0])
    vm = PyBoy(rom[0], window_type="headless")
    for i in range(2000):
        vm.tick()
    vm.save_state(open(rom[1], "wb"))

GIF_SHOOT_MODULUS = 8 # every frame a modules of this will be added to the gif
SCALE = 3 # scale the images up in size before sending to discord
COMMAND_PREFIX = '!'
CLEAN_IDLE_GAMES = False # if a game doesn't have input for an hour, clean it up
EMOJI_REACTIONS = [
    '⬆', # up arrow
    '⬇', # down arrow
    '⬅', # left arrow
    '➡', # right arrow
    '🅰', # a button
    '🅱', # b button
    '➖', # start
    '➕', # select
    '❌' # no input
]
REACTION_BUTTONS = [
    (WindowEvent.PRESS_ARROW_UP,        WindowEvent.RELEASE_ARROW_UP),
    (WindowEvent.PRESS_ARROW_DOWN,      WindowEvent.RELEASE_ARROW_DOWN),
    (WindowEvent.PRESS_ARROW_LEFT,      WindowEvent.RELEASE_ARROW_LEFT),
    (WindowEvent.PRESS_ARROW_RIGHT,     WindowEvent.RELEASE_ARROW_RIGHT),
    (WindowEvent.PRESS_BUTTON_A,        WindowEvent.RELEASE_BUTTON_A),
    (WindowEvent.PRESS_BUTTON_B,        WindowEvent.RELEASE_BUTTON_B),
    (WindowEvent.PRESS_BUTTON_START,    WindowEvent.RELEASE_BUTTON_START),
    (WindowEvent.PRESS_BUTTON_SELECT,   WindowEvent.RELEASE_BUTTON_SELECT),
    (None,                              None)
] # corresponds with EMOJI_REACTIONS
WHITELISTED_USERS = [
    168807635737378816
] # users that have permissions in all servers to run commands
WHITELISTED_CHANNELS = [
    726144063845302411,
    726512748103729183,
    725884904147124355,
    726181851705638963,
    726356601065177158
] # channels that won't be cleaned up auto-matically
ACTIVE_CHANNELS = {}

# make sure the saves directory exists
if not os.path.exists("./saves"):
    os.makedirs("./saves")

def activateChannel(id, rom):
    # start our vm, this vm is exclusive to this channel ONLY
    vm = PyBoy(ROMS[rom][0], window_type="headless", debug=False)
    vm.set_emulation_speed(0) # don't delay for anything, just compute the instructions as fast as possible

    vm.load_state(open(ROMS[rom][1], "rb"))

    ACTIVE_CHANNELS[id] = {}
    ACTIVE_CHANNELS[id]["active"] = True
    ACTIVE_CHANNELS[id]["rom"] = rom
    ACTIVE_CHANNELS[id]["vm"] = vm
    ACTIVE_CHANNELS[id]["frames"] = ROMS[rom][2]
    ACTIVE_CHANNELS[id]["state"] = io.BytesIO(open(ROMS[rom][1], "rb").read()) # copy default state
    #ACTIVE_CHANNELS[id]["state"] = io.BytesIO()
    ACTIVE_CHANNELS[id]["state"].seek(0)

def saveState(id):
    with open("./saves/" + ACTIVE_CHANNELS[id]["rom"] + str(id), "wb") as outfile:
        outfile.seek(0)
        outfile.write(ACTIVE_CHANNELS[id]["state"].getvalue())

def getScreenCap(vm):
    return vm.botsupport_manager().screen().screen_image().resize((160*SCALE, 144*SCALE), resample=Image.BOX)

# start our discord bot
client = Bot(description="Play GameBoy games with friends! :)", command_prefix=COMMAND_PREFIX, pm_help = False)

# call this everytime a game is started or stoped
async def status_change():
    await client.change_presence(activity=discord.Game(str(len(ACTIVE_CHANNELS)) + " gameboy games | !help"))

async def runGame(channel):
    vm = ACTIVE_CHANNELS[channel.id]["vm"]
    # all of these try, except are because discord.py loves to throw errors if things aren't *exactly* the way it expects it to be. 
    # we NEED to clean up the vm NO MATTER WHAT! otherwise, it'll never get cleaned up by python's garbage collector and we'll run out
    # of memory. memory is precious, esp. on a raspberry pi with spotty internet connection so discord.py throws errors like it's at a rave.

    try:
        await status_change()
    except:
        ACTIVE_CHANNELS[channel.id]["active"] = False

    try:
        while ACTIVE_CHANNELS[channel.id]["active"]:
            message = None
            async with channel.typing(): # while we are loading the state & emulating 30 frames (1 second of gameplay)
                frames = []

                # press button down for 1/4 a second
                if "prebutton" in ACTIVE_CHANNELS[channel.id] and ACTIVE_CHANNELS[channel.id]["prebutton"] != None:
                    vm.send_input(ACTIVE_CHANNELS[channel.id]["prebutton"])

                for i in range(15):
                    vm.tick()
                    if i % GIF_SHOOT_MODULUS == 0: # add a screen capture to the frame queue
                        frames.append(getScreenCap(vm))

                if "postbutton" in ACTIVE_CHANNELS[channel.id] and ACTIVE_CHANNELS[channel.id]["postbutton"] != None:
                    vm.send_input(ACTIVE_CHANNELS[channel.id]["postbutton"])

                for i in range(ACTIVE_CHANNELS[channel.id]["frames"] - 15):
                    vm.tick()
                    if (i+15) % GIF_SHOOT_MODULUS == 0: # add a screen capture to the frame queue (we add 15 to match our previous frames)
                        frames.append(getScreenCap(vm))

                ACTIVE_CHANNELS[channel.id]["state"].seek(0)
                vm.save_state(ACTIVE_CHANNELS[channel.id]["state"])
                ACTIVE_CHANNELS[channel.id]["state"].seek(0)

                # final frame screenshot
                frames.append(getScreenCap(vm))

                # take the screenshot
                tmpImage = io.BytesIO()
                tmpImage.seek(0)
                frames.insert(0, frames[len(frames)-1]) # set preview to the last frame
                frames[0].save(tmpImage, format='GIF', append_images=frames[1:], save_all=True, duration=((1000 * (ACTIVE_CHANNELS[channel.id]["frames"] / 60)) / len(frames)-1), optimize=True)
                tmpImage.seek(0)

                reactionTry = 5
                while reactionTry > 0:
                    try:
                        # send screenshot to the channel
                        message = await channel.send(file=discord.File(tmpImage, filename="scrn.gif"))

                        # add reactions to message
                        for emoji in EMOJI_REACTIONS:
                            await message.add_reaction(emoji)

                        reactionTry = 0
                    except:
                        if message != None:
                            await message.delete()

                        reactionTry = reactionTry - 1

            waited_log = 0
            while ACTIVE_CHANNELS[channel.id]["active"]:
                waited_log += 1

               # if no activity for an hour, close session.
                if CLEAN_IDLE_GAMES and channel.id not in WHITELISTED_CHANNELS and waited_log > 720:
                    ACTIVE_CHANNELS[channel.id]["active"] = False
                    saveState(channel.id)
                    await channel.send("> ⛔ game has been stopped due to inactivity. saved state!")
                    break

                # wait for reactions
                await asyncio.sleep(5)
                message = await channel.fetch_message(message.id)
                most_reacted = (None, 1)
                for reaction in message.reactions:
                    if str(reaction) in EMOJI_REACTIONS: # is a valid reaction
                        if (most_reacted[1] < reaction.count):
                            most_reacted = (str(reaction), reaction.count)
                    else:
                        continue

                if most_reacted[1] == 1: # no reactions, wait for 5 more seconds
                    continue

                ACTIVE_CHANNELS[channel.id]["prebutton"] = REACTION_BUTTONS[EMOJI_REACTIONS.index(most_reacted[0])][0]
                ACTIVE_CHANNELS[channel.id]["postbutton"] = REACTION_BUTTONS[EMOJI_REACTIONS.index(most_reacted[0])][1]

                # quit reaction loop :)
                break;
            # deletes the message
            await message.delete()
    except:
        saveState(channel.id)
        try:
            await channel.send("> ⛔ game crashed or forced shutdown! however state was saved, restore the save using load.")
            ACTIVE_CHANNELS[channel.id]["active"] = False
        except:
            pass

    try:
        # we're no longer wanted!! kill it!
        vm.stop(save=False) # we have our own saving implementation, saving states.
        del ACTIVE_CHANNELS[channel.id]
        await channel.send("> ✅ thanks for playing!")
        await status_change()
    except:
        pass

@client.event
async def on_ready():
    print(client.user.name + ' is ready!')
    await status_change()

class ROMSTATE(commands.Cog, name='ROM running/loading/saving'):
    """Deals with loading/saving/running ROMs"""

    @commands.command(pass_context = True, help="Starts the ROM, if ROM is omitted PKM_RED will be started", usage="(ROM)")
    @commands.guild_only()
    async def start(self, ctx, rom = "pkm_red"):
        if ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS:
            rom = rom.lower()
            if not rom in ROMS:
                await ctx.message.channel.send("> ⛔ game '" + rom + "' not found! use 'list' to get a list of roms.")
                return
            if ctx.message.channel.id in ACTIVE_CHANNELS:
                await ctx.message.channel.send("> ⛔ game is already running in this channel! use 'stop' to stop the current game.")
                return

            await ctx.message.channel.send("> ✅ starting '" + rom.upper() + "'!")
            activateChannel(ctx.message.channel.id, rom)
            await runGame(ctx.message.channel)

    @commands.command(pass_context = True, help="Stops the current ROM")
    @commands.guild_only()
    async def stop(self, ctx):
        if (ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS) and ctx.message.channel.id in ACTIVE_CHANNELS:
            ACTIVE_CHANNELS[ctx.message.channel.id]["active"] = False

    @commands.command(pass_context = True, help="Force stops the current ROM. You *might* LOSE ALL PROGRESS.")
    @commands.guild_only()
    async def forcestop(self, ctx):
        if (ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS) and ctx.message.channel.id in ACTIVE_CHANNELS:
            ACTIVE_CHANNELS[ctx.message.channel.id]["vm"].stop(save=False)
            del ACTIVE_CHANNELS[ctx.message.channel.id]
            await status_change()
            await ctx.message.channel.send("> ✅ force stoped successfully!")

    @commands.command(pass_context = True, help="Saves the current state of the ROM to the channel")
    @commands.guild_only()
    async def save(self, ctx):
        if (ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS) and ctx.message.channel.id in ACTIVE_CHANNELS:
            saveState(ctx.message.channel.id)
            await ctx.message.channel.send("> ✅ saved state successfully!")

    @commands.command(pass_context = True, help="Loads ROM with saved state, if ROM is omitted PKM_RED will be used.", usage="(ROM)")
    @commands.guild_only()
    async def load(self, ctx, rom = "pkm_red"):
        if ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS:
            rom = rom.lower()
            if not rom in ROMS:
                await ctx.message.channel.send("> ⛔ game '" + rom + "' not found! use 'list' to get a list of ROMs.")
                return

            if ctx.message.channel.id in ACTIVE_CHANNELS:
                await ctx.message.channel.send("> ⛔ cannot load state while game is running! use 'stop' to stop the current game.")
                return
            
            if os.path.exists("./saves/" + rom + str(ctx.message.channel.id)):
                with open("./saves/" + rom + str(ctx.message.channel.id), "rb") as infile:
                    activateChannel(ctx.message.channel.id, rom)

                    # load file into state
                    await ctx.message.channel.send("> ✅ starting '" + rom.upper() + "'!")
                    ACTIVE_CHANNELS[ctx.message.channel.id]["vm"].load_state(infile)
                    await runGame(ctx.message.channel) # start game
            else:
                await ctx.message.channel.send("> ⛔ no state was saved!")

class REACTCONTROL(commands.Cog, name='Reaction button controls'):
    """Category for commands for buttons"""

    @commands.command(pass_context = True, help="Lists controls")
    @commands.guild_only()
    async def controls(self, ctx):
        strng = "`Here's a list of the controls:`\n"
        for i in range(len(EMOJI_REACTIONS)):
            strng += "> " + EMOJI_REACTIONS[i] + "\t"

            if REACTION_BUTTONS[i][0] == WindowEvent.PRESS_ARROW_UP:
                strng += "UP"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_ARROW_DOWN:
                strng += "DOWN"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_ARROW_LEFT:
                strng += "LEFT"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_ARROW_RIGHT:
                strng += "RIGHT"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_BUTTON_A:
                strng += "A BUTTON"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_BUTTON_B:
                strng += "B BUTTON"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_BUTTON_START:
                strng += "START"
            elif REACTION_BUTTONS[i][0] == WindowEvent.PRESS_BUTTON_SELECT:
                strng += "SELECT"
            elif REACTION_BUTTONS[i][0] == None:
                strng += "NO INPUT"
            else:
                strng += "ERR"
            
            strng += "\n"
        
        await ctx.message.channel.send(strng)

class MEMMANIP(commands.Cog, name='Gameboy Memory manipulation'):
    """Category for commands that allow you to manipulate memory in the gameboy"""

    @commands.command(pass_context = True, help="Writes BYTE to ADDRESS in RAM", usage="[ADDRESS] [BYTE]")
    @commands.guild_only()
    async def write(self, ctx, addr, value):
        addr = addr.replace("0x", "")
        value = value.replace("0x", "")

        if (ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS) and ctx.message.channel.id in ACTIVE_CHANNELS:
            try:
                ACTIVE_CHANNELS[ctx.message.channel.id]["vm"].set_memory_value(int(addr, 16), int(value, 16))
            except:
                await ctx.message.channel.send("> ⛔ failed to write to 0x" + addr + "!")
                return
            
            await ctx.message.channel.send("> ✅ wrote 0x" + value + " to 0x" + addr + " successfully!")
    
    @commands.command(pass_context = True, help="Reads BYTE from ADDRESS in RAM", usage="[ADDRESS]")
    @commands.guild_only()
    async def read(self, ctx, addr):
        addr = addr.replace("0x", "")

        if (ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS) and ctx.message.channel.id in ACTIVE_CHANNELS:
            try:
                res = ACTIVE_CHANNELS[ctx.message.channel.id]["vm"].get_memory_value(int(addr, 16))
                await ctx.message.channel.send("> 0x" + addr + " : " + str(hex(res)))
            except:
                await ctx.message.channel.send("> ⛔ failed to read " + addr)
                return

@client.command(pass_context = True, name='list', help="Lists all available ROMs")
@commands.guild_only()
async def _list(ctx):
    if ctx.message.author.guild_permissions.administrator or ctx.message.author.id in WHITELISTED_USERS:
        strng = "Here are a list of the avalible roms:```\n"
        i = 0
        for rom in ROMS:
            i+=1
            strng = strng + str(i) + ". " + rom.upper() + "\n"
        strng += "```"
        await ctx.message.channel.send(strng)

client.add_cog(ROMSTATE())
client.add_cog(MEMMANIP())
client.add_cog(REACTCONTROL())
client.run(open("token.txt", "r").readline())
