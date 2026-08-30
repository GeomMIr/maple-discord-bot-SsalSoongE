import discord
from discord.ext import commands
from discord import app_commands

class PartyScheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.auto_thursday_vote.start() # (이미 있는 스케줄러 실행 코드)

    # ==========================================
    # 1. 수동 호출 (슬래시 커맨드: /고정팟투표)
    # ==========================================
    @app_commands.command(name="고정팟투표", description="고정 파티 일정 투표를 시작합니다.")
    async def force_vote_ui(self, interaction: discord.Interaction):
        # ⭐ 핵심 1: 3초 타임아웃 방지를 위해 먼저 '생각 중...' 띄우기
        # ephemeral=True로 하면 명령어를 친 사람에게만 보입니다.
        await interaction.response.defer(ephemeral=True) 

        try:
            # 뷰(View) 객체 생성 (기존에 사용하시던 클래스명으로 맞춰주세요)
            view = YourVoteViewClass() # 예: PartySelectView()

            # ⭐ 핵심 2: defer를 썼으므로 response.send_message가 아닌 followup.send 사용
            await interaction.followup.send(
                "📢 **고정 파티 일정 투표**\n투표를 시작할 고정 파티를 선택해주세요.", 
                view=view
            )
        except Exception as e:
            await interaction.followup.send(f"투표 UI를 불러오는 중 오류가 발생했습니다: {e}")

    # ==========================================
    # 2. 자동 호출 (목요일 스케줄러)
    # ==========================================
    # (이미 사용 중이신 @tasks.loop 나 apscheduler 함수 부분입니다)
    async def auto_thursday_vote(self):
        # 투표 메시지를 보낼 채널 ID 입력
        TARGET_CHANNEL_ID = 123456789012345678  # 실제 공지 채널 ID로 변경
        
        channel = self.bot.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            print("투표를 보낼 채널을 찾을 수 없습니다.")
            return

        try:
            # 뷰(View) 객체 생성
            view = YourVoteViewClass() # 예: PartySelectView()

            # ⭐ 핵심 3: 스케줄러는 interaction이 없으므로 채널에 직접 전송 (channel.send)
            await channel.send(
                "📢 **[정기 알림] 이번 주 고정 파티 일정 투표**\n투표를 시작할 고정 파티를 선택해주세요.", 
                view=view
            )
        except Exception as e:
            print(f"자동 투표 전송 중 오류 발생: {e}")

async def setup(bot):
    await bot.add_cog(PartyScheduler(bot))