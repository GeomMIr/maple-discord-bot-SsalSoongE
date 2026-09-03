import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import aiohttp
import json
import calendar
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 고정팟 투표 시스템 UI (대시보드 방식)
# ==========================================

class TimeSelectView(discord.ui.View):
    def __init__(self, dashboard, targets, title_context="선택한 날짜"):
        super().__init__(timeout=86400)
        self.dashboard = dashboard
        self.targets = targets

        base_times = dashboard.accumulated_data.get(targets[0], [])

        options = [discord.SelectOption(label="✅ 전부 (24시간 가능)", value="all")]
        for h in range(24):
            start = f"{str(h).zfill(2)}:00"
            end = f"{str((h+1)%24).zfill(2)}:00" if h < 23 else "24:00"
            is_def = start in base_times
            options.append(discord.SelectOption(label=f"{start} ~ {end}", value=start, default=is_def))

        self.sel = discord.ui.Select(
            placeholder=f"⏰ {title_context}에 가능한 시간을 선택 (복수 선택)", 
            min_values=1, 
            max_values=25, 
            options=options, 
            row=0
        )
        self.sel.callback = self.on_sel
        self.add_item(self.sel)

        btn_save = discord.ui.Button(label="💾 저장하고 메인으로", style=discord.ButtonStyle.success, row=1)
        btn_clear = discord.ui.Button(label="🗑️ 시간 비우기", style=discord.ButtonStyle.danger, row=1)
        btn_back = discord.ui.Button(label="⬅️ 뒤로가기 (취소)", style=discord.ButtonStyle.secondary, row=1)

        btn_save.callback = self.on_save
        btn_clear.callback = self.on_clear
        btn_back.callback = self.on_back

        self.add_item(btn_save)
        self.add_item(btn_clear)
        self.add_item(btn_back)

    async def on_sel(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_save(self, interaction: discord.Interaction):
        vals = self.sel.values
        if not vals:
            return await interaction.response.send_message("시간을 선택하거나 '시간 비우기'를 눌러주세요.", ephemeral=True)

        if "all" in vals:
            final_times = [f"{str(h).zfill(2)}:00" for h in range(24)]
        else:
            final_times = vals

        for t in self.targets:
            self.dashboard.accumulated_data[t] = final_times

        await self.dashboard.update_message(interaction)

    async def on_clear(self, interaction: discord.Interaction):
        for t in self.targets:
            if t in self.dashboard.accumulated_data:
                del self.dashboard.accumulated_data[t]
        await self.dashboard.update_message(interaction)

    async def on_back(self, interaction: discord.Interaction):
        await self.dashboard.update_message(interaction)


class TargetSelectView(discord.ui.View):
    def __init__(self, dashboard):
        super().__init__(timeout=86400)
        self.dashboard = dashboard
        
        if dashboard.cycle == 'bossMonthly':
            opts1 = [discord.SelectOption(label=d, value=d) for d in dashboard.all_days[:15]]
            opts2 = [discord.SelectOption(label=d, value=d) for d in dashboard.all_days[15:]]
            
            self.sel1 = discord.ui.Select(placeholder="🗓️ 1일~15일 중 선택", min_values=0, max_values=len(opts1), options=opts1, row=0)
            self.sel2 = discord.ui.Select(placeholder="🗓️ 16일~말일 중 선택", min_values=0, max_values=len(opts2), options=opts2, row=1)
            self.sel1.callback = self.on_sel
            self.sel2.callback = self.on_sel
            self.add_item(self.sel1)
            self.add_item(self.sel2)
        else:
            opts = [discord.SelectOption(label=d, value=d) for d in dashboard.all_days]
            self.sel1 = discord.ui.Select(placeholder="🗓️ 세부 설정할 요일을 선택 (복수 선택)", min_values=0, max_values=len(opts), options=opts, row=0)
            self.sel1.callback = self.on_sel
            self.add_item(self.sel1)

        btn_next = discord.ui.Button(label="➡️ 시간 설정으로", style=discord.ButtonStyle.primary, row=2)
        btn_back = discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.secondary, row=2)

        btn_next.callback = self.on_next
        btn_back.callback = self.on_back
        self.add_item(btn_next)
        self.add_item(btn_back)

    async def on_sel(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_next(self, interaction: discord.Interaction):
        vals1 = self.sel1.values if hasattr(self, 'sel1') else []
        vals2 = self.sel2.values if hasattr(self, 'sel2') else []
        targets = vals1 + vals2
        
        if not targets:
            return await interaction.response.send_message("최소 1개 이상의 항목을 선택해주세요!", ephemeral=True)
            
        if self.dashboard.cycle == 'bossMonthly':
            targets.sort(key=lambda x: int(x.split("일")[0]))
        else:
            order = {"월":0, "화":1, "수":2, "목":3, "금":4, "토":5, "일":6}
            targets.sort(key=lambda x: order.get(x, 9))

        await interaction.response.edit_message(view=TimeSelectView(self.dashboard, targets, "선택한 항목"))

    async def on_back(self, interaction: discord.Interaction):
        await self.dashboard.update_message(interaction)


class VoteDashboardView(discord.ui.View):
    def __init__(self, cog, party_id, boss_name, user_id, cycle, accumulated_data=None):
        super().__init__(timeout=86400)
        self.cog = cog
        self.party_id = party_id
        self.boss_name = boss_name
        self.user_id = user_id
        self.cycle = cycle
        self.accumulated_data = accumulated_data or {}

        self.all_days = []
        self.weekdays = []
        self.weekends = []
        
        if cycle == 'bossMonthly':
            now = datetime.now(timezone(timedelta(hours=9)))
            _, last_day = calendar.monthrange(now.year, now.month)
            wd_names = ["월", "화", "수", "목", "금", "토", "일"]
            for d in range(1, last_day + 1):
                target = now.replace(day=d)
                idx = target.weekday()
                label = f"{d}일 ({wd_names[idx]})"
                self.all_days.append(label)
                if idx < 5: self.weekdays.append(label)
                else: self.weekends.append(label)
        else:
            self.all_days = ["월", "화", "수", "목", "금", "토", "일"]
            self.weekdays = ["월", "화", "수", "목", "금"]
            self.weekends = ["토", "일"]

        btn_wd = discord.ui.Button(label="🗓️ 평일 일괄 설정", style=discord.ButtonStyle.primary, row=0)
        btn_wk = discord.ui.Button(label="🎉 주말 일괄 설정", style=discord.ButtonStyle.primary, row=0)
        btn_cu = discord.ui.Button(label="🔍 세부 날짜 설정", style=discord.ButtonStyle.secondary, row=0)
        btn_sb = discord.ui.Button(label="✅ 최종 투표 제출", style=discord.ButtonStyle.success, row=1)

        btn_wd.callback = self.on_wd
        btn_wk.callback = self.on_wk
        btn_cu.callback = self.on_cu
        btn_sb.callback = self.on_submit

        self.add_item(btn_wd)
        self.add_item(btn_wk)
        self.add_item(btn_cu)
        self.add_item(btn_sb)

    def generate_embed(self):
        embed = discord.Embed(title=f"📊 [{self.boss_name}] 투표 컨트롤 패널", color=discord.Color.gold())
        desc = "**[현재 설정된 나의 일정]**\n"
        has_any = False
        
        for day in self.all_days:
            times = self.accumulated_data.get(day, [])
            if times:
                has_any = True
                merged = self.cog._merge_time_slots(times)
                desc += f"🔹 **{day}**: {merged}\n"
                
        if not has_any:
            desc += "아직 설정된 일정이 없습니다.\n위의 버튼을 눌러 가능한 시간을 추가해주세요."

        embed.description = desc
        return embed

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def on_wd(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=TimeSelectView(self, self.weekdays, "평일 전체"))

    async def on_wk(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=TimeSelectView(self, self.weekends, "주말 전체"))

    async def on_cu(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=TargetSelectView(self))

    async def on_submit(self, interaction: discord.Interaction):
        if not self.accumulated_data:
            return await interaction.response.send_message("최소 1개 이상의 일정을 설정한 후 제출해주세요!", ephemeral=True)

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
            embed=None, view=None
        )
        await self.cog.check_vote_completion(self.party_id)

    async def on_timeout(self):
        pass


# ==========================================
# 2. 고정팟 삭제/수동 투표/내 일정 수정 뷰
# ==========================================
class PartyActionSelectView(discord.ui.View):
    def __init__(self, cog, user_id, my_parties, action_type, target_channel_id=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.action_type = action_type
        self.target_channel_id = target_channel_id 
        
        emoji = "🗑️" if action_type == 'delete' else "📢" if action_type == 'vote' else "✏️"
        ph = "삭제할 파티" if action_type == 'delete' else "전체 재투표할 파티" if action_type == 'vote' else "일정을 수정할 파티"
        
        options = [discord.SelectOption(label=f"[{p_id}] {b_name}", value=str(p_id)) for p_id, b_name in my_parties[:25]]
        
        self.select_item = discord.ui.Select(placeholder=f"{emoji} {ph}를 선택하세요", min_values=1, max_values=1, options=options)
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

        elif self.action_type == 'edit_self':
            await interaction.response.defer()
            self.cog.c.execute('SELECT cycle FROM parties WHERE party_id = ?', (party_id,))
            cycle_row = self.cog.c.fetchone()
            cycle = cycle_row[0] if cycle_row and cycle_row[0] else 'bossWeekly'
            
            self.cog.c.execute('SELECT available_times FROM vote_records WHERE party_id = ? AND user_id = ?', (party_id, self.user_id))
            record_row = self.cog.c.fetchone()
            accumulated_data = json.loads(record_row[0]) if record_row else {}

            view = VoteDashboardView(self.cog, party_id, boss_name, self.user_id, cycle, accumulated_data)
            embed = view.generate_embed()
            try:
                user = self.cog.bot.get_user(self.user_id) or await self.cog.bot.fetch_user(self.user_id)
                await user.send(content=f"📢 **[{boss_name}] 내 일정 수정**\n아래 패널에서 일정을 수정하고 제출해주세요.", embed=embed, view=view)
                await interaction.followup.send(f"✅ **[{boss_name}]** 일정 수정 패널을 DM으로 발송했습니다!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("⚠️ DM 차단으로 인해 패널을 보낼 수 없습니다.", ephemeral=True)


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
        await interaction.response.defer()
        
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
        
        await interaction.edit_original_response(
            content=f"🎉 **[고정팟 ID: {party_id}]** 파티가 성공적으로 생성되었으며, 파티원들에게 초대 DM이 전송되었습니다!\n⚔️ **보스:** {self.boss_name}\n👥 **파티원 목록:**\n" + "\n".join([f"• {s}" for s in member_display_strs]), 
            view=None
        )

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
        
        if now.weekday() == 3 and now.hour == 10 and now.minute == 0:
            if getattr(self, "last_weekly_vote_date", None) != now.date():
                self.last_weekly_vote_date = now.date()
                await self._trigger_automated_votes('bossWeekly')
                
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

    @app_commands.command(name="고정팟투표", description="파티 전체에 새로운 일정 투표 DM을 발송합니다. (전체 재투표용)")
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
        await interaction.followup.send(f"📢 **고정 파티 전체 재투표**\n투표를 시작할 고정 파티를 선택해주세요.", view=view, ephemeral=True)

    @app_commands.command(name="내일정수정", description="파티 전체 투표를 초기화하지 않고, 내 일정만 수정하여 결과를 업데이트합니다.")
    async def edit_my_vote_ui(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.c.execute('''SELECT p.party_id, p.boss_name FROM parties p JOIN party_members m ON p.party_id = m.party_id WHERE m.user_id = ?''', (interaction.user.id,))
        my_parties = self.c.fetchall()
        if not my_parties: 
            return await interaction.followup.send("참여 중인 고정 파티가 없습니다.", ephemeral=True)
        
        view = PartyActionSelectView(self, interaction.user.id, my_parties, action_type='edit_self')
        await interaction.followup.send(f"✏️ **내 일정 수정**\n일정을 수정할 고정 파티를 선택해주세요.", view=view, ephemeral=True)

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
                view = VoteDashboardView(self, party_id, boss_name, m_id, cycle, {})
                embed = view.generate_embed()
                await user.send(content=f"📢 **[{boss_name}] 일정 조율 투표가 시작되었습니다!**\n아래 패널의 버튼을 눌러 일정을 추가/수정해주세요.", embed=embed, view=view)
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
            self.c.execute('SELECT guild_id, boss_name, cycle FROM parties WHERE party_id = ?', (party_id,))
            party_info = self.c.fetchone()
            if not party_info: return
            guild_id, boss_name, cycle = party_info[0], party_info[1], (party_info[2] or 'bossWeekly')

            self.c.execute('SELECT notice_channel_id FROM guild_settings WHERE guild_id = ?', (guild_id,))
            channel_row = self.c.fetchone()
            if not channel_row: return
            
            channel = self.bot.get_channel(channel_row[0])
            if not channel:
                try: channel = await self.bot.fetch_channel(channel_row[0])
                except: return

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

async def setup(bot):
    await bot.add_cog(PartyScheduler(bot))