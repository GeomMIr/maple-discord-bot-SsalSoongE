import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import aiohttp
import json
import calendar
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 고정팟 투표 시스템 UI (DM용 위저드)
# ==========================================

class VoteTimeSelectView(discord.ui.View):
    def __init__(self, cog, party_id, boss_name, user_id, days_list, current_index, accumulated_data, is_monthly=False):
        super().__init__(timeout=86400) 
        self.cog = cog
        self.party_id = party_id
        self.boss_name = boss_name
        self.user_id = user_id
        self.days_list = days_list
        self.current_index = current_index
        self.current_day = days_list[current_index]
        self.accumulated_data = accumulated_data
        self.is_monthly = is_monthly

        options = [discord.SelectOption(label="✅ 전부 (24시간 가능)", value="all")]
        for h in range(24):
            start = f"{str(h).zfill(2)}:00"
            end = f"{str((h+1)%24).zfill(2)}:00" if h < 23 else "24:00"
            options.append(discord.SelectOption(label=f"{start} ~ {end}", value=start))
        
        day_str = f"{self.current_day}에" if self.is_monthly else f"{self.current_day}요일에"
        
        self.select_item = discord.ui.Select(
            placeholder=f"⏰ {day_str} 가능한 시간을 모두 고르세요", 
            min_values=1, 
            max_values=25, 
            options=options
        )
        self.select_item.callback = self.select_callback
        self.add_item(self.select_item)

        is_last = (current_index == len(days_list) - 1)
        btn_label = "✅ 투표 완료" if is_last else "➡️ 다음 날로"
        btn_style = discord.ButtonStyle.success if is_last else discord.ButtonStyle.primary

        self.next_btn = discord.ui.Button(label=btn_label, style=btn_style)
        self.next_btn.callback = self.btn_callback
        self.add_item(self.next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def btn_callback(self, interaction: discord.Interaction):
        if not self.select_item.values:
            await interaction.response.send_message("최소 1개 이상의 시간을 선택해주세요!", ephemeral=True)
            return
            
        if "all" in self.select_item.values:
            selected_times = [f"{str(h).zfill(2)}:00" for h in range(24)]
        else:
            selected_times = self.select_item.values

        self.accumulated_data[self.current_day] = selected_times

        if self.current_index + 1 < len(self.days_list):
            next_view = VoteTimeSelectView(self.cog, self.party_id, self.boss_name, self.user_id, self.days_list, self.current_index + 1, self.accumulated_data, self.is_monthly)
            await interaction.response.edit_message(
                content=f"🗓️ **[{self.boss_name}] 일정 투표**\n({self.current_index + 2}/{len(self.days_list)}) **{self.days_list[self.current_index + 1]}**에 가능한 시간을 선택해주세요.",
                view=next_view
            )
            self.stop()
        else:
            self.stop()
            self.cog.c.execute('INSERT OR REPLACE INTO vote_records (party_id, user_id, available_times) VALUES (?, ?, ?)', 
                               (self.party_id, self.user_id, json.dumps(self.accumulated_data)))
            self.cog.conn.commit()
            
            self.cog.c.execute('SELECT COUNT(*) FROM vote_records WHERE party_id = ?', (self.party_id,))
            voted_count = self.cog.c.fetchone()[0]
            self.cog.c.execute('SELECT COUNT(*) FROM party_members WHERE party_id = ?', (self.party_id,))
            total_members = self.cog.c.fetchone()[0]

            await interaction.response.edit_message(
                content=f"🎉 **[{self.boss_name}] 투표가 완료되었습니다!**\n📊 현재 투표 현황: **{voted_count} / {total_members}명** 완료\n모든 파티원이 투표를 마치면 지정된 채널에 결과가 공지됩니다.",
                view=None
            )
            
            await self.cog.check_vote_completion(self.party_id)

    async def on_timeout(self):
        self.cog.c.execute('SELECT 1 FROM vote_sessions WHERE party_id = ?', (self.party_id,))
        if self.cog.c.fetchone():
            self.cog.c.execute('DELETE FROM vote_sessions WHERE party_id = ?', (self.party_id,))
            self.cog.c.execute('DELETE FROM vote_records WHERE party_id = ?', (self.party_id,))
            self.cog.conn.commit()
            
            self.cog.c.execute('SELECT user_id FROM party_members WHERE party_id = ?', (self.party_id,))
            for (m_id,) in self.cog.c.fetchall():
                try:
                    user = self.cog.bot.get_user(m_id) or await self.cog.bot.fetch_user(m_id)
                    await user.send(f"⚠️ **[{self.boss_name}]** 파티의 일정 투표가 **1일**이 지나 만료되었습니다.\n투표가 완료되지 않아 세션이 종료되었으니, 디스코드 서버 채팅창에서 `/고정팟투표` 명령어를 입력해 재투표를 진행해주세요!")
                except:
                    pass

class VoteDateSelectView(discord.ui.View):
    def __init__(self, cog, party_id, boss_name, user_id):
        super().__init__(timeout=86400)
        self.cog = cog
        self.party_id = party_id
        self.boss_name = boss_name
        self.user_id = user_id

        now = datetime.now(timezone(timedelta(hours=9)))
        _, last_day = calendar.monthrange(now.year, now.month)
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        
        options1, options2 = [], []
        
        for d in range(1, last_day + 1):
            target_date = now.replace(day=d)
            wd_str = weekdays[target_date.weekday()]
            label = f"{d}일 ({wd_str})"
            opt = discord.SelectOption(label=label, value=label)
            if d <= 15:
                options1.append(opt)
            else:
                options2.append(opt)

        self.select1 = discord.ui.Select(placeholder="🗓️ 1일 ~ 15일 중 가능한 날짜", min_values=0, max_values=len(options1), options=options1, row=0)
        self.select1.callback = self.select_callback
        self.add_item(self.select1)

        if options2:
            self.select2 = discord.ui.Select(placeholder=f"🗓️ 16일 ~ {last_day}일 중 가능한 날짜", min_values=0, max_values=len(options2), options=options2, row=1)
            self.select2.callback = self.select_callback
            self.add_item(self.select2)

        self.next_btn = discord.ui.Button(label="➡️ 다음 단계 (시간 선택)", style=discord.ButtonStyle.primary, row=2)
        self.next_btn.callback = self.btn_callback
        self.add_item(self.next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def btn_callback(self, interaction: discord.Interaction):
        vals1 = self.select1.values if hasattr(self, 'select1') else []
        vals2 = self.select2.values if hasattr(self, 'select2') else []
        total_vals = vals1 + vals2
        
        if not total_vals:
            return await interaction.response.send_message("최소 1개 이상의 날짜를 선택해주세요!", ephemeral=True)

        sorted_dates = sorted(total_vals, key=lambda x: int(x.split("일")[0]))

        next_view = VoteTimeSelectView(self.cog, self.party_id, self.boss_name, self.user_id, sorted_dates, 0, {}, is_monthly=True)
        await interaction.response.edit_message(
            content=f"🗓️ **[{self.boss_name}] 일정 투표**\n(1/{len(sorted_dates)}) **{sorted_dates[0]}**에 가능한 시간을 선택해주세요.",
            view=next_view
        )
        self.stop()

    async def on_timeout(self):
        self.cog.c.execute('SELECT 1 FROM vote_sessions WHERE party_id = ?', (self.party_id,))
        if self.cog.c.fetchone():
            self.cog.c.execute('DELETE FROM vote_sessions WHERE party_id = ?', (self.party_id,))
            self.cog.c.execute('DELETE FROM vote_records WHERE party_id = ?', (self.party_id,))
            self.cog.conn.commit()
            
            self.cog.c.execute('SELECT user_id FROM party_members WHERE party_id = ?', (self.party_id,))
            for (m_id,) in self.cog.c.fetchall():
                try:
                    user = self.cog.bot.get_user(m_id) or await self.cog.bot.fetch_user(m_id)
                    await user.send(f"⚠️ **[{self.boss_name}]** 파티의 일정 투표가 **1일**이 지나 만료되었습니다.\n투표가 완료되지 않아 세션이 종료되었으니, 디스코드 서버 채팅창에서 `/고정팟투표` 명령어를 입력해 재투표를 진행해주세요!")
                except: pass

class VoteDaySelectView(discord.ui.View):
    def __init__(self, cog, party_id, boss_name, user_id):
        super().__init__(timeout=86400) 
        self.cog = cog
        self.party_id = party_id
        self.boss_name = boss_name
        self.user_id = user_id

        days = ["월", "화", "수", "목", "금", "토", "일"]
        options = [discord.SelectOption(label=f"{d}요일", value=d) for d in days]

        self.select_item = discord.ui.Select(
            placeholder="🗓️ 가능한 요일을 모두 고르세요", 
            min_values=1, 
            max_values=7, 
            options=options
        )
        self.select_item.callback = self.select_callback
        self.add_item(self.select_item)

        self.next_btn = discord.ui.Button(label="➡️ 다음 단계 (시간 선택)", style=discord.ButtonStyle.primary)
        self.next_btn.callback = self.btn_callback
        self.add_item(self.next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def btn_callback(self, interaction: discord.Interaction):
        if not self.select_item.values:
            return await interaction.response.send_message("최소 1개 이상의 요일을 선택해주세요!", ephemeral=True)

        day_order = {"월":0, "화":1, "수":2, "목":3, "금":4, "토":5, "일":6}
        selected_days = sorted(self.select_item.values, key=lambda x: day_order[x])

        next_view = VoteTimeSelectView(self.cog, self.party_id, self.boss_name, self.user_id, selected_days, 0, {}, is_monthly=False)
        await interaction.response.edit_message(
            content=f"🗓️ **[{self.boss_name}] 일정 투표**\n(1/{len(selected_days)}) **{selected_days[0]}요일**에 가능한 시간을 선택해주세요.",
            view=next_view
        )
        self.stop()

    async def on_timeout(self):
        self.cog.c.execute('SELECT 1 FROM vote_sessions WHERE party_id = ?', (self.party_id,))
        if self.cog.c.fetchone():
            self.cog.c.execute('DELETE FROM vote_sessions WHERE party_id = ?', (self.party_id,))
            self.cog.c.execute('DELETE FROM vote_records WHERE party_id = ?', (self.party_id,))
            self.cog.conn.commit()
            
            self.cog.c.execute('SELECT user_id FROM party_members WHERE party_id = ?', (self.party_id,))
            for (m_id,) in self.cog.c.fetchall():
                try:
                    user = self.cog.bot.get_user(m_id) or await self.bot.fetch_user(m_id)
                    await user.send(f"⚠️ **[{self.boss_name}]** 파티의 일정 투표가 **1일**이 지나 만료되었습니다.\n투표가 완료되지 않아 세션이 종료되었으니, 디스코드 서버 채팅창에서 `/고정팟투표` 명령어를 입력해 재투표를 진행해주세요!")
                except: pass

# ==========================================
# 2. 고정팟 삭제/수동 투표 뷰
# ==========================================
class PartyActionSelectView(discord.ui.View):
    def __init__(self, cog, user_id, my_parties, action_type, target_channel_id=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.action_type = action_type
        self.target_channel_id = target_channel_id 
        
        emoji = "🗑️" if action_type == 'delete' else "📢"
        ph = "삭제할 파티를 선택하세요" if action_type == 'delete' else "투표를 진행할 파티를 선택하세요"
        
        options = [discord.SelectOption(label=f"[{p_id}] {b_name}", value=str(p_id)) for p_id, b_name in my_parties[:25]]
        
        self.select_item = discord.ui.Select(placeholder=f"{emoji} {ph}", min_values=1, max_values=1, options=options)
        self.select_item.callback = self.action_callback
        self.add_item(self.select_item)

    async def action_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
            
        party_id = int(self.select_item.values[0])
        self.cog.c.execute('SELECT boss_name FROM parties WHERE party_id = ?', (party_id,))
        party_row = self.cog.c.fetchone()
        boss_name = party_row[0] if party_row else "알 수 없는 보스"
        
        if self.action_type == 'delete':
            self.cog.c.execute('SELECT user_id, character_name FROM party_members WHERE party_id = ?', (party_id,))
            members = self.cog.c.fetchall()
            self.cog.c.execute('DELETE FROM parties WHERE party_id = ?', (party_id,))
            self.cog.c.execute('DELETE FROM party_members WHERE party_id = ?', (party_id,))
            self.cog.conn.commit()

            for m_id, m_char in members:
                try:
                    user = self.cog.bot.get_user(m_id) or await self.cog.bot.fetch_user(m_id)
                    if user: await user.send(f"⚠️ **[안내]** 참여 중이셨던 **[{boss_name}] (고정팟 ID: {party_id})** 파티가 삭제되었습니다.")
                except: pass
            await interaction.response.edit_message(content=f"🗑️ **[{boss_name}] (ID: {party_id})** 고정 파티가 삭제되었으며, 멤버들에게 알림이 전송되었습니다.", view=None)
            
        elif self.action_type == 'vote':
            await interaction.response.defer()
            failed_members = await self.cog._execute_vote(party_id, boss_name, self.target_channel_id)
            
            msg = f"✅ **[{boss_name}]** 파티원 전원에게 수동 투표 DM을 발송했습니다!"
            if failed_members: msg += f"\n⚠️ 다음 유저는 DM 차단으로 인해 발송하지 못했습니다: {', '.join(failed_members)}"
            await interaction.followup.send(content=msg, ephemeral=True)


# ==========================================
# 3. 파티 생성 위저드
# ==========================================
class PartyCreateModal(discord.ui.Modal, title="고정 파티 생성 - 캐릭터 설정"):
    def __init__(self, cog, user_id, char_name, boss_name, cycle, selected_members, guild):
        super().__init__()
        self.cog = cog
        self.user_id = user_id
        self.char_name = char_name
        self.boss_name = boss_name
        self.cycle = cycle
        self.selected_members = selected_members
        self.guild = guild

        self.inputs = {}
        for m_id in selected_members[:5]:
            member = guild.get_member(m_id)
            m_name = member.display_name if member else f"유저_{m_id}"
            self.cog.c.execute('SELECT char_name FROM characters WHERE discord_id = ? LIMIT 1', (m_id,))
            c_row = self.cog.c.fetchone()
            text_input = discord.ui.TextInput(label=f"{m_name[:15]} 캐릭터명", placeholder="메이플 캐릭터명 (없으면 닉네임)", default=c_row[0] if c_row else "", required=False, max_length=20)
            self.add_item(text_input)
            self.inputs[m_id] = text_input

    async def on_submit(self, interaction: discord.Interaction):
        self.cog.c.execute('INSERT INTO parties (guild_id, boss_name, cycle) VALUES (?, ?, ?)', (self.guild.id, self.boss_name, self.cycle))
        party_id = self.cog.c.lastrowid
        self.cog.c.execute('INSERT INTO party_members (party_id, user_id, character_name) VALUES (?, ?, ?)', (party_id, self.user_id, self.char_name))
        
        party_members_data = [(self.user_id, self.char_name)]
        for m_id in self.selected_members[:5]:
            if m_id == self.user_id: continue
            input_val = self.inputs[m_id].value.strip() or (self.guild.get_member(m_id).display_name if self.guild.get_member(m_id) else f"유저_{m_id}")
            self.cog.c.execute('INSERT INTO party_members (party_id, user_id, character_name) VALUES (?, ?, ?)', (party_id, m_id, input_val))
            party_members_data.append((m_id, input_val))
        self.cog.conn.commit()

        for m_id, m_char in party_members_data:
            try:
                user = self.cog.bot.get_user(m_id) or await self.cog.bot.fetch_user(m_id)
                prefix = "[월간]" if self.cycle == "bossMonthly" else "[주간]"
                if user: await user.send(f"🎉 **[고정팟 생성/초대 알림]**\n**{prefix} {self.boss_name}** 고정 파티(ID: {party_id})에 참여되었습니다!\n지정된 캐릭터: **{m_char}**")
            except: pass

        member_display_strs = [f"<@{m_id}> ({m_char})" for m_id, m_char in party_members_data]
        await interaction.response.edit_message(content=f"🎉 **[고정팟 ID: {party_id}]** 파티가 성공적으로 생성되었으며, 파티원들에게 초대 DM이 전송되었습니다!\n⚔️ **보스:** {self.boss_name}\n👥 **파티원 목록:**\n" + "\n".join([f"• {s}" for s in member_display_strs]), view=None)

class PartyMemberSelectView(discord.ui.View):
    def __init__(self, cog, user_id, char_name, boss_name, cycle, guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.char_name = char_name
        self.boss_name = boss_name
        self.cycle = cycle
        self.guild = guild
        members = [m for m in guild.members if not m.bot][:25]
        
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members] if members else [discord.SelectOption(label="불러올 수 있는 멤버가 없습니다.", value="error")]
        is_disabled = not bool(members)

        self.select_item = discord.ui.Select(placeholder="👥 함께 갈 파티원들을 선택하세요" if not is_disabled else "❌ 멤버 정보를 불러올 수 없습니다", min_values=1, max_values=1 if is_disabled else max(1, len(options)), options=options, disabled=is_disabled)
        self.select_item.callback = self.member_callback
        self.add_item(self.select_item)

    async def member_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        if self.select_item.values[0] == "error": return await interaction.response.send_message("⚠️ 멤버 목록을 불러올 수 없어 파티원을 선택할 수 없습니다.", ephemeral=True)

        selected_member_ids = [int(uid) for uid in self.select_item.values]
        if self.user_id not in selected_member_ids: selected_member_ids.insert(0, self.user_id)
        await interaction.response.send_modal(PartyCreateModal(self.cog, self.user_id, self.char_name, self.boss_name, self.cycle, selected_member_ids, self.guild))

class BossSelectView(discord.ui.View):
    def __init__(self, cog, user_id, char_name, boss_options, guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.char_name = char_name
        self.guild = guild
        self.select_item = discord.ui.Select(placeholder="⚔️ 고정으로 갈 보스를 선택하세요", min_values=1, max_values=1, options=boss_options)
        self.select_item.callback = self.boss_callback
        self.add_item(self.select_item)

    async def boss_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        
        cycle, boss_name = self.select_item.values[0].split("||")
        
        await interaction.response.edit_message(content=f"⚔️ 선택한 캐릭터: **{self.char_name}**\n⚔️ 선택한 보스: **{boss_name}**\n이제 함께 파티를 꾸릴 **파티원들**을 선택해주세요.", view=PartyMemberSelectView(self.cog, self.user_id, self.char_name, boss_name, cycle, self.guild))

class CharSelectView(discord.ui.View):
    def __init__(self, cog, user_id, api_key, chars, guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.api_key = api_key
        self.guild = guild
        options = [discord.SelectOption(label=c, value=c) for c in chars[:25]]
        self.select_item = discord.ui.Select(placeholder="🎮 사용할 본인 캐릭터를 선택하세요", min_values=1, max_values=1, options=options)
        self.select_item.callback = self.char_callback
        self.add_item(self.select_item)

    async def char_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("본인만 조작할 수 있습니다!", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        char_name = self.select_item.values[0]
        boss_options = await self.cog._get_boss_list(self.api_key, char_name)
        if not boss_options or len(boss_options) == 0: return await interaction.followup.send("❌ 해당 캐릭터에 체크(등록)되어 있는 주간/월간 보스가 없습니다!", ephemeral=True)
        await interaction.edit_original_response(content=f"🎮 선택한 캐릭터: **{char_name}**\n고정으로 갈 보스를 선택해주세요.", view=BossSelectView(self.cog, self.user_id, char_name, boss_options, self.guild))


# ==========================================
# 4. 메인 코그 클래스 (자동화 포함)
# ==========================================
class PartyScheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('maple_bot.db', check_same_thread=False)
        self.c = self.conn.cursor()
        self._create_tables()
        self.vote_task.start()

    def cog_unload(self):
        self.vote_task.cancel()

    def _create_tables(self):
        self.c.execute('''CREATE TABLE IF NOT EXISTS parties (party_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, boss_name TEXT)''')
        
        try:
            self.c.execute("ALTER TABLE parties ADD COLUMN cycle TEXT DEFAULT 'bossWeekly'")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass 

        try:
            self.c.execute("ALTER TABLE parties ADD COLUMN guild_id INTEGER")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

        self.c.execute('''CREATE TABLE IF NOT EXISTS party_members (party_id INTEGER, user_id INTEGER, character_name TEXT, PRIMARY KEY (party_id, user_id))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS vote_sessions (party_id INTEGER PRIMARY KEY, channel_id INTEGER)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS vote_records (party_id INTEGER, user_id INTEGER, available_times TEXT, PRIMARY KEY (party_id, user_id))''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS guild_settings (guild_id INTEGER PRIMARY KEY, notice_channel_id INTEGER)''')
        self.conn.commit()

    @tasks.loop(minutes=1)
    async def vote_task(self):
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        
        # 💡 주간 보스: 매주 목요일 오전 10시
        if now.weekday() == 3 and now.hour == 10 and now.minute == 0:
            if getattr(self, "last_weekly_vote_date", None) != now.date():
                self.last_weekly_vote_date = now.date()
                await self._trigger_automated_votes('bossWeekly')
                
        # 💡 월간 보스: 매월 1일 오전 10시
        if now.day == 1 and now.hour == 10 and now.minute == 0:
            if getattr(self, "last_monthly_vote_date", None) != now.date():
                self.last_monthly_vote_date = now.date()
                await self._trigger_automated_votes('bossMonthly')

    @vote_task.before_loop
    async def before_vote_task(self):
        await self.bot.wait_until_ready() 

    async def _trigger_automated_votes(self, target_cycle):
        self.c.execute('''
            SELECT p.party_id, p.boss_name, g.notice_channel_id 
            FROM parties p 
            JOIN guild_settings g ON p.guild_id = g.guild_id
            WHERE p.cycle = ? OR (p.cycle IS NULL AND ? = 'bossWeekly')
        ''', (target_cycle, target_cycle))
        parties = self.c.fetchall()
        
        for party_id, boss_name, channel_id in parties:
            await self._execute_vote(party_id, boss_name, channel_id)

    async def _get_boss_list(self, api_key: str, char_name: str):
        headers = {"accept": "application/json", "x-nxopen-api-key": api_key}
        async with aiohttp.ClientSession() as session:
            ocid_url = f"https://open.api.nexon.com/maplestory/v1/id?character_name={char_name}"
            async with session.get(ocid_url, headers=headers) as resp:
                if resp.status != 200: return None
                ocid = (await resp.json()).get("ocid")

            sched_url = f"https://open.api.nexon.com/maplestory/v1/scheduler/character-state?ocid={ocid}"
            async with session.get(sched_url, headers=headers) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                
                monthly_bosses = []
                weekly_bosses = []
                
                for b in data.get("boss_contents", []):
                    if b.get("registration_flag") == "true":
                        boss_name = b.get("content_name", "")
                        cycle = b.get("cycle")
                        
                        if "시즌 보스" in boss_name or cycle == "bossDaily": continue
                        
                        prefix = "주간" if cycle == "bossWeekly" else "월간"
                        diff = b['difficulty'].upper()
                        label = f"[{prefix}] {boss_name} ({diff})"
                        value = f"{cycle}||{boss_name} ({diff})"
                        opt = discord.SelectOption(label=label, value=value)
                        
                        if cycle == "bossMonthly":
                            if not any(o.value == value for o in monthly_bosses):
                                monthly_bosses.append(opt)
                        else:
                            if not any(o.value == value for o in weekly_bosses):
                                weekly_bosses.append(opt)
                
                boss_options = monthly_bosses + weekly_bosses
                return boss_options[:25]

    @app_commands.command(name="고정팟생성", description="내 캐릭터를 골라 보스를 선택하고 고정 파티를 생성합니다.")
    async def create_party(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.c.execute('SELECT api_key FROM users WHERE discord_id = ?', (user_id,))
        user_row = self.c.fetchone()
        if not user_row: return await interaction.response.send_message("⚠️ API 키가 없습니다. `/api등록`을 먼저 진행해주세요.", ephemeral=True)
        
        self.c.execute('SELECT char_name FROM characters WHERE discord_id = ?', (user_id,))
        my_chars = [row[0] for row in self.c.fetchall()]
        if not my_chars: return await interaction.response.send_message("⚠️ 등록된 캐릭터가 없습니다. `/캐릭터등록`을 먼저 진행해주세요.", ephemeral=True)

        view = CharSelectView(self, user_id, user_row[0], my_chars, interaction.guild)
        await interaction.response.send_message("🧙‍♂️ **고정 파티 생성 마법사**\n1단계: 파티에 사용할 본인의 메이플 캐릭터를 선택해주세요.", view=view, ephemeral=True)

    @app_commands.command(name="고정팟목록", description="내가 속한 고정 파티 목록을 조회합니다.")
    async def list_parties(self, interaction: discord.Interaction):
        self.c.execute('SELECT party_id FROM party_members WHERE user_id = ?', (interaction.user.id,))
        my_party_ids = [row[0] for row in self.c.fetchall()]
        if not my_party_ids: return await interaction.response.send_message("참여 중인 고정 파티가 없습니다.", ephemeral=True)

        embed = discord.Embed(title="🛡️ 내 고정 파티 목록", color=discord.Color.blue())
        for p_id in my_party_ids:
            self.c.execute('SELECT boss_name, cycle FROM parties WHERE party_id = ?', (p_id,))
            row = self.c.fetchone()
            b_name = row[0]
            prefix = "[월간]" if len(row) > 1 and row[1] == "bossMonthly" else "[주간]"
            
            self.c.execute('SELECT user_id, character_name FROM party_members WHERE party_id = ?', (p_id,))
            member_strs = [f"<@{m[0]}> ({m[1]})" for m in self.c.fetchall()]
            embed.add_field(name=f"📌 {prefix} {b_name} (ID: {p_id})", value="파티원:\n" + ("\n".join(member_strs)), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="고정팟삭제", description="내가 속한 고정 파티 중 하나를 삭제합니다.")
    async def delete_party_ui(self, interaction: discord.Interaction):
        self.c.execute('''SELECT p.party_id, p.boss_name FROM parties p JOIN party_members m ON p.party_id = m.party_id WHERE m.user_id = ?''', (interaction.user.id,))
        my_parties = self.c.fetchall()
        if not my_parties: return await interaction.response.send_message("삭제할 고정 파티가 없습니다.", ephemeral=True)
        view = PartyActionSelectView(self, interaction.user.id, my_parties, action_type='delete')
        await interaction.response.send_message("🗑️ **고정 파티 삭제**\n삭제할 고정 파티를 선택해주세요.", view=view, ephemeral=True)

    @app_commands.command(name="고정팟채널지정", description="고정 파티 투표 결과가 공지될 텍스트 채널을 설정합니다.")
    async def set_notice_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild_id is None:
            return await interaction.response.send_message("서버 내에서만 사용할 수 있는 명령어입니다.", ephemeral=True)
            
        self.c.execute('INSERT OR REPLACE INTO guild_settings (guild_id, notice_channel_id) VALUES (?, ?)', (interaction.guild_id, channel.id))
        self.conn.commit()
        await interaction.response.send_message(f"✅ 앞으로 고정팟 일정 투표 결과는 {channel.mention} 채널에 공지됩니다!\n(주간 보스는 매주 목요일, 월간 보스는 매월 1일에 자동 투표 DM이 발송됩니다.)")

    @app_commands.command(name="고정팟투표", description="내가 속한 파티원들에게 일정 투표 DM을 발송합니다. (일정 변동 시 재투표용)")
    async def force_vote_ui(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        if interaction.guild_id is None:
            return await interaction.followup.send("서버 내에서만 사용할 수 있는 명령어입니다.", ephemeral=True)
            
        self.c.execute('SELECT notice_channel_id FROM guild_settings WHERE guild_id = ?', (interaction.guild_id,))
        row = self.c.fetchone()
        if not row:
            return await interaction.followup.send("⚠️ 투표 결과를 올릴 공지 채널이 지정되지 않았습니다.\n`/고정팟채널지정` 명령어로 알림을 받을 채널을 먼저 설정해주세요.", ephemeral=True)
        
        target_channel_id = row[0]
        
        self.c.execute('''SELECT p.party_id, p.boss_name FROM parties p JOIN party_members m ON p.party_id = m.party_id WHERE m.user_id = ?''', (interaction.user.id,))
        my_parties = self.c.fetchall()
        if not my_parties: 
            return await interaction.followup.send("투표를 시작할 파티가 없습니다.", ephemeral=True)
        
        view = PartyActionSelectView(self, interaction.user.id, my_parties, action_type='vote', target_channel_id=target_channel_id)
        await interaction.followup.send(f"📢 **고정 파티 일정 투표**\n투표를 시작할 고정 파티를 선택해주세요.", view=view, ephemeral=True)

    async def _execute_vote(self, party_id, boss_name, channel_id):
        self.c.execute('DELETE FROM vote_records WHERE party_id = ?', (party_id,))
        self.c.execute('INSERT OR REPLACE INTO vote_sessions (party_id, channel_id) VALUES (?, ?)', (party_id, channel_id))
        
        self.c.execute('SELECT cycle FROM parties WHERE party_id = ?', (party_id,))
        cycle_row = self.c.fetchone()
        cycle = cycle_row[0] if cycle_row and cycle_row[0] else 'bossWeekly'
        self.conn.commit()

        self.c.execute('SELECT user_id FROM party_members WHERE party_id = ?', (party_id,))
        members = [row[0] for row in self.c.fetchall()]

        failed_members = []
        for m_id in members:
            try:
                user = self.bot.get_user(m_id) or await self.bot.fetch_user(m_id)
                if cycle == 'bossMonthly':
                    view = VoteDateSelectView(self, party_id, boss_name, m_id)
                    msg = f"📢 **[{boss_name}] (월간) 일정 조율 투표가 시작되었습니다!**\n가장 먼저, 이번 달 레이드가 가능한 **날짜**를 모두 골라주세요."
                else:
                    view = VoteDaySelectView(self, party_id, boss_name, m_id)
                    msg = f"📢 **[{boss_name}] 일정 조율 투표가 시작되었습니다!**\n가장 먼저, 이번 주 레이드가 가능한 **요일**을 모두 골라주세요."
                await user.send(msg, view=view)
            except:
                failed_members.append(f"<@{m_id}>")
                
        return failed_members

    def _merge_time_slots(self, time_list):
        if len(time_list) == 24:
            return "전부 (24시간 가능)"
            
        hours = sorted([int(t.split(":")[0]) for t in time_list])
        if not hours: return ""

        merged = []
        start = hours[0]
        prev = hours[0]

        for h in hours[1:]:
            if h == prev + 1:
                prev = h
            else:
                end_hour = prev + 1
                end_str = f"{str(end_hour).zfill(2)}:00" if end_hour < 24 else "24:00"
                merged.append(f"{str(start).zfill(2)}:00 ~ {end_str}")
                start = h
                prev = h

        end_hour = prev + 1
        end_str = f"{str(end_hour).zfill(2)}:00" if end_hour < 24 else "24:00"
        merged.append(f"{str(start).zfill(2)}:00 ~ {end_str}")

        return ", ".join(merged)

    async def check_vote_completion(self, party_id):
        self.c.execute('SELECT COUNT(*) FROM party_members WHERE party_id = ?', (party_id,))
        total_members = self.c.fetchone()[0]
        
        self.c.execute('SELECT user_id, available_times FROM vote_records WHERE party_id = ?', (party_id,))
        records = self.c.fetchall()
        
        if len(records) >= total_members:
            self.c.execute('SELECT channel_id FROM vote_sessions WHERE party_id = ?', (party_id,))
            channel_row = self.c.fetchone()
            if not channel_row: return
            
            channel = self.bot.get_channel(channel_row[0])
            if not channel:
                try: channel = await self.bot.fetch_channel(channel_row[0])
                except: return

            self.c.execute('SELECT boss_name, cycle FROM parties WHERE party_id = ?', (party_id,))
            party_info = self.c.fetchone()
            boss_name = party_info[0]
            cycle = party_info[1] if len(party_info) > 1 and party_info[1] else 'bossWeekly'

            all_votes = [json.loads(r[1]) for r in records]
            
            common_days = set(all_votes[0].keys())
            for vote in all_votes[1:]:
                common_days = common_days.intersection(set(vote.keys()))

            if cycle == 'bossMonthly':
                sorted_days = sorted(common_days, key=lambda x: int(x.split("일")[0]) if "일" in x else 99)
            else:
                sorted_days = sorted(common_days, key=lambda x: {"월":0, "화":1, "수":2, "목":3, "금":4, "토":5, "일":6}.get(x, 99))

            results_text = ""
            for day in sorted_days:
                common_times = set(all_votes[0][day])
                for vote in all_votes[1:]:
                    common_times = common_times.intersection(set(vote[day]))
                
                if common_times:
                    merged_str = self._merge_time_slots(list(common_times))
                    if cycle == 'bossMonthly':
                        results_text += f"\n🔹 **{day}**: {merged_str}"
                    else:
                        results_text += f"\n🔹 **{day}요일**: {merged_str}"

            embed = discord.Embed(title=f"📊 [{boss_name}] 고정팟 투표 결과", color=discord.Color.green())
            if results_text:
                embed.description = f"🎉 **파티원 전원이 가능한 시간대입니다!**\n{results_text}"
            else:
                embed.description = "😢 **파티원 전원이 공통으로 가능한 시간이 없습니다.**\n채널에서 다시 일정을 조율해 보세요!"

            mentions_text = " ".join([f"<@{r[0]}>" for r in records])
            
            await channel.send(content=mentions_text, embed=embed)
            
            self.c.execute('DELETE FROM vote_sessions WHERE party_id = ?', (party_id,))
            self.c.execute('DELETE FROM vote_records WHERE party_id = ?', (party_id,))
            self.conn.commit()

async def setup(bot):
    await bot.add_cog(PartyScheduler(bot))