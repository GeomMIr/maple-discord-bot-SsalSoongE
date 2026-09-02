import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta, time

class AlertSelectView(discord.ui.View):
    def __init__(self, cog, user_id, existing_schedules, fixed_alert_status):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.fixed_alert_status = fixed_alert_status
        
        self.saved_days = list(set([s[0] for s in existing_schedules]))
        self.saved_times = list(set([s[1] for s in existing_schedules]))
        self.selected_days = self.saved_days.copy()
        self.selected_times = self.saved_times.copy()

        day_options = [
            discord.SelectOption(label="월요일", value="월", default=("월" in self.saved_days)),
            discord.SelectOption(label="화요일", value="화", default=("화" in self.saved_days)),
            discord.SelectOption(label="수요일", value="수", default=("수" in self.saved_days)),
            discord.SelectOption(label="목요일", value="목", default=("목" in self.saved_days)),
            discord.SelectOption(label="금요일", value="금", default=("금" in self.saved_days)),
            discord.SelectOption(label="토요일", value="토", default=("토" in self.saved_days)),
            discord.SelectOption(label="일요일", value="일", default=("일" in self.saved_days)),
        ]
        
        self.day_select = discord.ui.Select(placeholder="📅 요일을 선택하세요 (복수 선택 가능)", min_values=1, max_values=7, options=day_options, row=0)
        self.day_select.callback = self.select_day_callback
        self.add_item(self.day_select)

        time_options = []
        for h in range(24):
            time_str = f"{h:02d}:00"
            time_options.append(discord.SelectOption(label=f"{time_str}", value=time_str, default=(time_str in self.saved_times)))
            
        self.time_select = discord.ui.Select(placeholder="⏰ 시간대를 선택하세요 (1시간 단위)", min_values=1, max_values=24, options=time_options, row=1)
        self.time_select.callback = self.select_time_callback
        self.add_item(self.time_select)

        # 💡 주간/월간 고정 알림 토글 버튼 추가
        toggle_style = discord.ButtonStyle.green if self.fixed_alert_status else discord.ButtonStyle.secondary
        toggle_label = "✅ 고정 알림 (수/말일): ON" if self.fixed_alert_status else "❌ 고정 알림 (수/말일): OFF"
        self.toggle_btn = discord.ui.Button(label=toggle_label, style=toggle_style, row=2)
        self.toggle_btn.callback = self.toggle_callback
        self.add_item(self.toggle_btn)

        self.save_btn = discord.ui.Button(label="💾 개인 알림 설정 저장", style=discord.ButtonStyle.primary, row=2)
        self.save_btn.callback = self.save_callback
        self.add_item(self.save_btn)

    async def select_day_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        self.selected_days = self.day_select.values
        await interaction.response.defer()

    async def select_time_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        self.selected_times = self.time_select.values
        await interaction.response.defer()

    async def toggle_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        
        self.fixed_alert_status = not self.fixed_alert_status
        self.toggle_btn.style = discord.ButtonStyle.green if self.fixed_alert_status else discord.ButtonStyle.secondary
        self.toggle_btn.label = "✅ 고정 알림 (수/말일): ON" if self.fixed_alert_status else "❌ 고정 알림 (수/말일): OFF"

        self.cog.c.execute('REPLACE INTO alert_settings (discord_id, fixed_alert) VALUES (?, ?)', (self.user_id, int(self.fixed_alert_status)))
        self.cog.conn.commit()
        await interaction.response.edit_message(view=self)

    async def save_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)

        self.cog.c.execute('DELETE FROM schedules WHERE discord_id = ?', (self.user_id,))
        for day in self.selected_days:
            for t in self.selected_times:
                self.cog.c.execute('INSERT INTO schedules (discord_id, day_of_week, time) VALUES (?, ?, ?)', (self.user_id, day, t))
        self.cog.conn.commit()
        
        days_str = ", ".join(self.selected_days) if self.selected_days else "없음"
        times_str = ", ".join(self.selected_times) if self.selected_times else "없음"
        await interaction.response.send_message(f"✅ **개인 알림 설정이 업데이트되었습니다!**\n📅 **요일:** {days_str}\n⏰ **시간:** {times_str}", ephemeral=True)
        self.stop()

class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('maple_bot.db')
        self.c = self.conn.cursor()
        self._create_tables()
        self.schedule_loop.start()
        self.fixed_alert_loop.start()

    def _create_tables(self):
        # 기존 schedules 테이블[cite: 1]
        self.c.execute('''CREATE TABLE IF NOT EXISTS schedules 
                          (discord_id INTEGER, day_of_week TEXT, time TEXT, 
                           PRIMARY KEY (discord_id, day_of_week, time))''')
        # 새로운 고정 알림 설정 테이블
        self.c.execute('''CREATE TABLE IF NOT EXISTS alert_settings 
                          (discord_id INTEGER PRIMARY KEY, fixed_alert INTEGER)''')
        self.conn.commit()

    async def _get_hw_embed(self, api_key: str, char_name: str, alert_type: str = "all"):
        headers = {"accept": "application/json", "x-nxopen-api-key": api_key}
        async with aiohttp.ClientSession() as session:
            ocid_url = f"https://open.api.nexon.com/maplestory/v1/id?character_name={char_name}"
            async with session.get(ocid_url, headers=headers) as ocid_resp:
                if ocid_resp.status != 200: return None
                ocid_data = await ocid_resp.json()
                ocid = ocid_data.get("ocid")

            sched_url = f"https://open.api.nexon.com/maplestory/v1/scheduler/character-state?ocid={ocid}"
            async with session.get(sched_url, headers=headers) as sched_resp:
                if sched_resp.status != 200: return None
                data = await sched_resp.json()
                
                boss_list = data.get("boss_contents", [])
                incomplete_weekly, incomplete_monthly = [], []
                
                for boss in boss_list:
                    boss_name = boss.get("content_name", "")
                    if "시즌 보스" in boss_name: continue
                        
                    if boss.get("registration_flag") == "true" and boss.get("complete_flag") == "false":
                        boss_str = f"• {boss_name} ({boss['difficulty'].upper()})"
                        if boss.get("cycle") == "bossMonthly":
                            incomplete_monthly.append(boss_str)
                        elif boss.get("cycle") == "bossWeekly":
                            incomplete_weekly.append(boss_str)
                
                clear_count = data.get("weekly_boss_clear_count", 0)
                limit_count = data.get("weekly_boss_clear_limit_count", 12)
                
                weekly_contents = data.get("weekly_contents", [])
                incomplete_guild = []
                for content in weekly_contents:
                    c_name = content.get("content_name", "")
                    if c_name in ["[길드] 지하 수로", "[길드] 플래그 레이스"] and content.get("now_count", 0) == 0:
                        incomplete_guild.append(f"• {c_name} (미완료)")
                            
                embed = discord.Embed(title=f"📝 {char_name}님의 숙제 현황", color=discord.Color.red())
                
                if alert_type in ["all", "weekly"]:
                    if clear_count >= limit_count:
                        embed.add_field(name="⚔️ 주간 보스", value=f"✅ 결정석 {limit_count}/{limit_count} 모두 완료하셨습니다!", inline=False)
                    elif incomplete_weekly:
                        embed.add_field(name=f"⚔️ 남은 주간 보스 (결정석 {clear_count}/{limit_count})", value="\n".join(incomplete_weekly), inline=False)
                    else:
                        embed.add_field(name="⚔️ 주간 보스", value="✅ 모두 완료하셨습니다!", inline=False)
                        
                    if incomplete_guild:
                        embed.add_field(name="🛡️ 남은 길드 컨텐츠", value="\n".join(incomplete_guild), inline=False)
                    else:
                        embed.add_field(name="🛡️ 길드 컨텐츠", value="✅ 모두 완료하셨습니다!", inline=False)

                if alert_type in ["all", "monthly"]:
                    if incomplete_monthly:
                        embed.add_field(name="🌑 남은 월간 보스", value="\n".join(incomplete_monthly), inline=False)
                    else:
                        embed.add_field(name="🌑 월간 보스", value="✅ 모두 완료하셨습니다!", inline=False)

                return embed

    @app_commands.command(name="숙제확인", description="캐릭터의 남은 숙제를 즉시 확인합니다.")
    async def check_hw(self, interaction: discord.Interaction, char_name: str):
        await interaction.response.defer(ephemeral=True)
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (interaction.user.id,))
        row = self.c.fetchone()
        if not row: return await interaction.followup.send("⚠️ API 키가 없습니다. `/api등록`을 진행해주세요.")
            
        embed = await self._get_hw_embed(row[0], char_name, alert_type="all")
        if embed: await interaction.followup.send(embed=embed)
        else: await interaction.followup.send("❌ 데이터를 불러오지 못했습니다.")

    @app_commands.command(name="알림설정", description="UI를 통해 간편하게 알림 받을 요일과 시간을 설정/수정합니다.")
    async def set_alert_ui(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.c.execute('SELECT day_of_week, time FROM schedules WHERE discord_id = ?', (user_id,))
        existing_schedules = self.c.fetchall()
        
        self.c.execute('SELECT fixed_alert FROM alert_settings WHERE discord_id = ?', (user_id,))
        alert_row = self.c.fetchone()
        fixed_alert_status = bool(alert_row[0]) if alert_row else False
        
        view = AlertSelectView(self, user_id, existing_schedules, fixed_alert_status)
        await interaction.response.send_message(
            "🔔 **알림 설정 메뉴**\n개인 스케줄을 선택 후 `저장`을 누르거나, `고정 알림` 스위치를 눌러 숙제 알림을 켜고 끌 수 있습니다.", 
            view=view, ephemeral=True
        )

    @app_commands.command(name="알림목록", description="등록된 알림 스케줄을 확인합니다.")
    async def list_alert(self, interaction: discord.Interaction):
        self.c.execute('SELECT day_of_week, time FROM schedules WHERE discord_id = ? ORDER BY day_of_week, time', (interaction.user.id,))
        rows = self.c.fetchall()
        
        self.c.execute('SELECT fixed_alert FROM alert_settings WHERE discord_id = ?', (interaction.user.id,))
        alert_row = self.c.fetchone()
        fixed_status = "ON 🟢" if alert_row and alert_row[0] else "OFF 🔴"
        
        msg = f"🔔 **고정 알림 (수/말일):** {fixed_status}\n\n📅 **내 개인 알림 목록**\n"
        if not rows: msg += "등록된 알림이 없습니다."
        else: msg += "\n".join([f"• {r[0]}요일 {r[1]}" for r in rows])
        
        await interaction.response.send_message(msg, ephemeral=True)

    @tasks.loop(minutes=1)
    async def schedule_loop(self):
        tz = timezone(timedelta(hours=9))
        now = datetime.now(tz)
        days_map = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
        
        self.c.execute('SELECT discord_id FROM schedules WHERE day_of_week = ? AND time = ?', (days_map[now.weekday()], now.strftime("%H:%M")))
        for (user_id,) in self.c.fetchall():
            await self._send_alerts_to_user(user_id, alert_type="all")

    @tasks.loop(time=time(hour=20, minute=0, tzinfo=timezone(timedelta(hours=9))))
    async def fixed_alert_loop(self):
        now = datetime.now(timezone(timedelta(hours=9)))
        tomorrow = now + timedelta(days=1)
        
        # 💡 매월 마지막 날인지 계산 (내일의 '월'이 오늘의 '월'과 다르면 오늘이 마지막 날)
        is_last_day = tomorrow.month != now.month
        is_wednesday = now.weekday() == 2

        if not (is_wednesday or is_last_day): return

        alert_type = "weekly" if is_wednesday else "monthly"
        msg_prefix = "🔔 **[주간 숙제 알림]** 내일 초기화 전 잊지 마세요!\n" if is_wednesday else "🚨 **[월간 보스 알림]** 달이 끝나가고 있습니다!\n"

        # 고정 알림 스위치를 ON(1)으로 해둔 유저만 검색
        self.c.execute('SELECT discord_id FROM alert_settings WHERE fixed_alert = 1')
        for (user_id,) in self.c.fetchall():
            await self._send_alerts_to_user(user_id, alert_type, msg_prefix)

    async def _send_alerts_to_user(self, user_id, alert_type, msg_prefix=""):
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (user_id,))
        api_row = self.c.fetchone()
        if not api_row: return
            
        self.c.execute('SELECT char_name FROM characters WHERE discord_id = ?', (user_id,))
        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        if not user: return

        for (char_name,) in self.c.fetchall():
            embed = await self._get_hw_embed(api_row[0], char_name, alert_type=alert_type)
            if embed:
                try:
                    await user.send(content=msg_prefix, embed=embed)
                    await asyncio.sleep(1)
                except discord.Forbidden: pass

    @schedule_loop.before_loop
    @fixed_alert_loop.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Scheduler(bot))