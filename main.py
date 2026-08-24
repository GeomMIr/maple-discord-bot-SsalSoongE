import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# .env 파일의 환경 변수를 불러옵니다.
load_dotenv()

# 환경 변수에서 토큰 값을 안전하게 가져옵니다.
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    # 봇이 켜질 때 cogs 폴더의 모듈들을 자동으로 불러오는 기능
    async def setup_hook(self):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
        await self.tree.sync() # 슬래시 명령어 동기화

bot = MyBot()

@bot.event
async def on_ready():
    print(f'✅ 로그인 완료: {bot.user}')

# 맨 아래 봇 실행 부분
bot.run(TOKEN)