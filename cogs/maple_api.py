import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import aiohttp
import json  # <--- 이 줄을 추가!

class MapleAPI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 모듈이 로드될 때 DB 연결
        self.conn = sqlite3.connect('maple_bot.db')
        self.c = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.c.execute('''CREATE TABLE IF NOT EXISTS users (discord_id INTEGER PRIMARY KEY, api_key TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS characters (discord_id INTEGER, char_name TEXT, PRIMARY KEY (discord_id, char_name))''')
        self.conn.commit()

    # ----------------------------------------------------
    # 여기서부터 명령어! (self 인자가 추가되었습니다)
    # ----------------------------------------------------
    
    @app_commands.command(name="api등록", description="본인의 넥슨 API 키를 등록합니다. (본인만 보임)")
    @app_commands.describe(api_key="넥슨 개발자 센터에서 발급받은 API 키")
    async def api_register(self, interaction: discord.Interaction, api_key: str):
        user_id = interaction.user.id
        self.c.execute('REPLACE INTO users (discord_id, api_key) VALUES (?, ?)', (user_id, api_key))
        self.conn.commit()
        await interaction.response.send_message("✅ API 키가 성공적으로 등록되었습니다!", ephemeral=True)

    @app_commands.command(name="api삭제", description="등록된 넥슨 API 키를 서버에서 삭제합니다.")
    async def api_delete(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.c.execute('DELETE FROM users WHERE discord_id = ?', (user_id,))
        self.conn.commit()
        await interaction.response.send_message("🗑️ 등록된 API 키가 삭제되었습니다.", ephemeral=True)

    @app_commands.command(name="캐릭터등록", description="알림을 받을 캐릭터명을 등록합니다.")
    @app_commands.describe(char_name="등록할 메이플스토리 캐릭터명")
    async def char_register(self, interaction: discord.Interaction, char_name: str):
        user_id = interaction.user.id
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (user_id,))
        if not self.c.fetchone():
            await interaction.response.send_message("⚠️ 먼저 `/api등록` 명령어로 API 키를 등록해주세요.", ephemeral=True)
            return

        try:
            self.c.execute('INSERT INTO characters (discord_id, char_name) VALUES (?, ?)', (user_id, char_name))
            self.conn.commit()
            await interaction.response.send_message(f"✅ '{char_name}' 캐릭터가 목록에 추가되었습니다.", ephemeral=True)
        except sqlite3.IntegrityError:
            await interaction.response.send_message("⚠️ 이미 등록되어 있는 캐릭터입니다.", ephemeral=True)

    @app_commands.command(name="캐릭터삭제", description="등록된 캐릭터를 목록에서 삭제합니다.")
    @app_commands.describe(char_name="삭제할 캐릭터명")
    async def char_delete(self, interaction: discord.Interaction, char_name: str):
        user_id = interaction.user.id
        self.c.execute('DELETE FROM characters WHERE discord_id = ? AND char_name = ?', (user_id, char_name))
        if self.c.rowcount > 0:
            self.conn.commit()
            await interaction.response.send_message(f"🗑️ '{char_name}' 캐릭터가 목록에서 삭제되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 목록에 해당 캐릭터가 존재하지 않습니다.", ephemeral=True)

    @app_commands.command(name="캐릭터목록", description="등록된 캐릭터들의 상세 정보를 조회합니다.")
    async def char_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (user_id,))
        user_row = self.c.fetchone()
        if not user_row:
            await interaction.followup.send("⚠️ 등록된 API 키가 없습니다. `/api등록`을 먼저 진행해주세요.")
            return
        api_key = user_row[0]

        self.c.execute('SELECT char_name FROM characters WHERE discord_id = ?', (user_id,))
        registered_chars = [row[0] for row in self.c.fetchall()]
        
        if not registered_chars:
            await interaction.followup.send("⚠️ 등록된 캐릭터가 없습니다. `/캐릭터등록`을 먼저 진행해주세요.")
            return

        url = "https://open.api.nexon.com/maplestory/v1/character/list"
        headers = {"accept": "application/json", "x-nxopen-api-key": api_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # 💡 수정된 핵심 부분: account_list 안의 모든 캐릭터를 하나의 리스트로 합칩니다.
                    api_char_list = []
                    for account in data.get("account_list", []):
                        api_char_list.extend(account.get("character_list", []))
                    
                    # 임베드(Embed) 메시지 꾸미기
                    embed = discord.Embed(title=f"📊 {interaction.user.display_name}님의 캐릭터 목록", color=discord.Color.blue())
                    
                    # DB에 등록한 캐릭터와 API 결과 매칭
                    for target_char in registered_chars:
                        match = next((item for item in api_char_list if item["character_name"] == target_char), None)
                        
                        if match:
                            embed.add_field(
                                name=f"Lv.{match['character_level']} {match['character_name']}",
                                value=f"서버: {match['world_name']} | 직업: {match['character_class']}",
                                inline=False
                            )
                        else:
                            embed.add_field(
                                name=f"❌ {target_char}",
                                value="해당 API 키의 계정에서 캐릭터를 찾을 수 없습니다.",
                                inline=False
                            )
                    
                    await interaction.followup.send(embed=embed)
                    
                # 💡 elif와 else는 if와 같은 세로줄에 있어야 합니다!
                elif resp.status in [401, 403]:
                    await interaction.followup.send("🚫 API 키가 유효하지 않거나 권한이 없습니다.")
                elif resp.status == 429:
                    await interaction.followup.send("⏳ API 호출 한도를 초과했습니다.")
                else:
                    await interaction.followup.send(f"❌ API 서버 에러가 발생했습니다. (코드: {resp.status})")

# 이 모듈을 main.py에서 불러올 수 있게 해주는 필수 함수
async def setup(bot):
    await bot.add_cog(MapleAPI(bot))

# 이 모듈을 main.py에서 불러올 수 있게 해주는 필수 함수
async def setup(bot):
    await bot.add_cog(MapleAPI(bot))