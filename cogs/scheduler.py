import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta

class AlertSelectView(discord.ui.View):
    def __init__(self, cog, user_id, existing_schedules):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        
        # 기존에 DB에 저장되어 있던 요일/시간 분리 (중복 제거)
        self.saved_days = list(set([s[0] for s in existing_schedules]))
        self.saved_times = list(set([s[1] for s in existing_schedules]))
        
        # 사용자가 최종 선택할 값을 저장할 변수 (기본값으로 기존 설정 세팅)
        self.selected_days = self.saved_days.copy()
        self.selected_times = self.saved_times.copy()

        # 1. 요일 드롭다운 동적 생성 (기존 설정 체크 반영)
        day_options = [
            discord.SelectOption(label="월요일", value="월", default=("월" in self.saved_days)),
            discord.SelectOption(label="화요일", value="화", default=("화" in self.saved_days)),
            discord.SelectOption(label="수요일", value="수", default=("수" in self.saved_days)),
            discord.SelectOption(label="목요일", value="목", default=("목" in self.saved_days)),
            discord.SelectOption(label="금요일", value="금", default=("금" in self.saved_days)),
            discord.SelectOption(label="토요일", value="토", default=("토" in self.saved_days)),
            discord.SelectOption(label="일요일", value="일", default=("일" in self.saved_days)),
        ]
        
        self.day_select = discord.ui.Select(
            placeholder="📅 요일을 선택하세요 (복수 선택 가능)",
            min_values=1,
            max_values=7,
            options=day_options,
            row=0
        )
        self.day_select.callback = self.select_day_callback
        self.add_item(self.day_select)

        # 2. 00시 ~ 23시 시간 드롭다운 동적 생성 (최대 25개 제한에 맞춤)
        time_options = []
        for h in range(24):
            time_str = f"{h:02d}:00"
            time_options.append(
                discord.SelectOption(label=f"{time_str}", value=time_str, default=(time_str in self.saved_times))
            )
            
        self.time_select = discord.ui.Select(
            placeholder="⏰ 시간대를 선택하세요 (1시간 단위)",
            min_values=1,
            max_values=24,
            options=time_options,
            row=1
        )
        self.time_select.callback = self.select_time_callback
        self.add_item(self.time_select)

    async def select_day_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
            return
        self.selected_days = self.day_select.values
        # 💡 요일 바꿀 때마다 오던 알림 메시지 제거 완료! (조용히 값만 담아둡니다)
        await interaction.response.defer()

    async def select_time_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
            return
        self.selected_times = self.time_select.values
        # 💡 시간 바꿀 때마다 오던 알림 메시지 제거 완료!
        await interaction.response.defer()

    # 3. 저장 버튼
    @discord.ui.button(label="💾 알림 설정 저장하기", style=discord.ButtonStyle.green, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
            return

        # 사용자의 기존 스케줄을 전부 지운 후, 새로 선택한 조합으로 덮어씌우기 (토글 방식 구현)
        self.cog.c.execute('DELETE FROM schedules WHERE discord_id = ?', (self.user_id,))
        
        for day in self.selected_days:
            for time in self.selected_times:
                self.cog.c.execute('INSERT INTO schedules (discord_id, day_of_week, time) VALUES (?, ?, ?)', (self.user_id, day, time))
                
        self.cog.conn.commit()
        
        days_str = ", ".join(self.selected_days) if self.selected_days else "없음"
        times_str = ", ".join(self.selected_times) if self.selected_times else "없음"
        
        await interaction.response.send_message(
            f"✅ **알림 설정이 성공적으로 업데이트되었습니다!**\n📅 **설정된 요일:** {days_str}\n⏰ **설정된 시간:** {times_str}", 
            ephemeral=True
        )
        self.stop()


class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('maple_bot.db')
        self.c = self.conn.cursor()
        self._create_tables()
        self.schedule_loop.start()

    def _create_tables(self):
        self.c.execute('''CREATE TABLE IF NOT EXISTS schedules 
                          (discord_id INTEGER, day_of_week TEXT, time TEXT, 
                           PRIMARY KEY (discord_id, day_of_week, time))''')
        self.conn.commit()

    async def _get_hw_embed(self, api_key: str, char_name: str):
        headers = {"accept": "application/json", "x-nxopen-api-key": api_key}
        async with aiohttp.ClientSession() as session:
            ocid_url = f"https://open.api.nexon.com/maplestory/v1/id?character_name={char_name}"
            async with session.get(ocid_url, headers=headers) as ocid_resp:
                if ocid_resp.status != 200:
                    return None
                ocid_data = await ocid_resp.json()
                ocid = ocid_data.get("ocid")

            sched_url = f"https://open.api.nexon.com/maplestory/v1/scheduler/character-state?ocid={ocid}"
            async with session.get(sched_url, headers=headers) as sched_resp:
                if sched_resp.status != 200:
                    return None
                data = await sched_resp.json()
                
                boss_list = data.get("boss_contents", [])
                incomplete_weekly, incomplete_monthly = [], []
                
                for boss in boss_list:
                    boss_name = boss.get("content_name", "")
                    if "시즌 보스" in boss_name:
                        continue
                        
                    if boss.get("registration_flag") == "true" and boss.get("complete_flag") == "false":
                        boss_str = f"• {boss_name} ({boss['difficulty'].upper()})"
                        cycle = boss.get("cycle")
                        if cycle == "bossMonthly":
                            incomplete_monthly.append(boss_str)
                        elif cycle == "bossWeekly":
                            incomplete_weekly.append(boss_str)
                
                clear_count = data.get("weekly_boss_clear_count", 0)
                limit_count = data.get("weekly_boss_clear_limit_count", 12)
                
                weekly_contents = data.get("weekly_contents", [])
                incomplete_guild = []
                for content in weekly_contents:
                    c_name = content.get("content_name", "")
                    if c_name in ["[길드] 지하 수로", "[길드] 플래그 레이스"]:
                        if content.get("now_count", 0) == 0:
                            incomplete_guild.append(f"• {c_name} (미완료)")
                            
                embed = discord.Embed(title=f"📝 {char_name}님의 숙제 현황", color=discord.Color.red())
                if incomplete_weekly:
                    embed.add_field(name=f"⚔️ 남은 주간 보스 (결정석 {clear_count}/{limit_count})", value="\n".join(incomplete_weekly), inline=False)
                else:
                    embed.add_field(name="⚔️ 주간 보스", value="✅ 모두 완료하셨습니다!", inline=False)
                    
                if incomplete_monthly:
                    embed.add_field(name="🌑 남은 월간 보스", value="\n".join(incomplete_monthly), inline=False)
                else:
                    embed.add_field(name="🌑 월간 보스", value="✅ 모두 완료하셨습니다!", inline=False)
                    
                if incomplete_guild:
                    embed.add_field(name="🛡️ 남은 길드 컨텐츠", value="\n".join(incomplete_guild), inline=False)
                else:
                    embed.add_field(name="🛡️ 길드 컨텐츠", value="✅ 모두 완료하셨습니다!", inline=False)

                return embed

    @app_commands.command(name="숙제확인", description="캐릭터의 남은 숙제를 즉시 확인합니다.")
    async def check_hw(self, interaction: discord.Interaction, char_name: str):
        await interaction.response.defer(ephemeral=True)
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (interaction.user.id,))
        row = self.c.fetchone()
        if not row:
            await interaction.followup.send("⚠️ API 키가 없습니다. `/api등록`을 진행해주세요.")
            return
            
        embed = await self._get_hw_embed(row[0], char_name)
        if embed:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ 데이터를 불러오지 못했습니다.")

    @app_commands.command(name="알림설정", description="UI를 통해 간편하게 알림 받을 요일과 시간을 설정/수정합니다.")
    async def set_alert_ui(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        # 현재 유저가 저장해 둔 기존 알림 불러오기
        self.c.execute('SELECT day_of_week, time FROM schedules WHERE discord_id = ?', (user_id,))
        existing_schedules = self.c.fetchall()
        
        view = AlertSelectView(self, user_id, existing_schedules)
        await interaction.response.send_message(
            "🔔 **알림 설정 및 수정 메뉴**\n원하시는 요일과 시간대를 선택하신 뒤 **[알림 설정 저장하기]** 버튼을 눌러주세요.\n*(기존에 설정했던 항목들은 체크되어 표시됩니다.)*", 
            view=view, 
            ephemeral=True
        )

    @app_commands.command(name="알림목록", description="등록된 알림 스케줄을 확인합니다.")
    async def list_alert(self, interaction: discord.Interaction):
        self.c.execute('SELECT day_of_week, time FROM schedules WHERE discord_id = ? ORDER BY day_of_week, time', (interaction.user.id,))
        rows = self.c.fetchall()
        if not rows:
            await interaction.response.send_message("등록된 알림이 없습니다.", ephemeral=True)
        else:
            sched_list = [f"• {r[0]}요일 {r[1]}" for r in rows]
            await interaction.response.send_message(f"📅 **내 알림 목록**\n" + "\n".join(sched_list), ephemeral=True)

    @tasks.loop(minutes=1)
    async def schedule_loop(self):
        tz = timezone(timedelta(hours=9))
        now = datetime.now(tz)
        
        days_map = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
        current_day = days_map[now.weekday()]
        current_time = now.strftime("%H:%M")

        self.c.execute('SELECT discord_id FROM schedules WHERE day_of_week = ? AND time = ?', (current_day, current_time))
        users_to_notify = [row[0] for row in self.c.fetchall()]

        for user_id in users_to_notify:
            self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (user_id,))
            api_row = self.c.fetchone()
            if not api_row:
                continue
                
            self.c.execute('SELECT char_name FROM characters WHERE discord_id = ?', (user_id,))
            char_rows = self.c.fetchall()
            
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if not user:
                continue

            for char_row in char_rows:
                char_name = char_row[0]
                embed = await self._get_hw_embed(api_row[0], char_name)
                if embed:
                    try:
                        await user.send(embed=embed)
                        await asyncio.sleep(1)
                    except discord.Forbidden:
                        print(f"⚠️ {user_id}에게 DM을 보낼 수 없습니다.")

    @schedule_loop.before_loop
    async def before_schedule_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Scheduler(bot))