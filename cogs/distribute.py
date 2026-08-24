import discord
from discord.ext import commands
from discord import app_commands
import math

# 클래스 바깥에 두어도 되는 도우미 함수
def format_meso(amount):
    """메소를 억, 만 단위로 읽기 쉽게 포맷팅하는 함수"""
    if amount == 0: return "0 메소"
    eok = amount // 100000000
    man = (amount % 100000000) // 10000
    rest = amount % 10000
    
    res = []
    if eok > 0: res.append(f"{eok}억")
    if man > 0: res.append(f"{man}만")
    if rest > 0: res.append(f"{rest}")
    
    return " ".join(res) + " 메소"

# 여기서부터가 명령어 부품 (Cog) 클래스입니다.
class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 💡 봇 객체(@bot.tree) 대신 앱 커맨드(@app_commands) 데코레이터를 사용합니다.
    # 💡 이 함수는 반드시 class 안으로 들여쓰기 되어야 합니다.
    @app_commands.command(name="분배", description="보스 수익을 인원수에 맞게 분배합니다.")
    @app_commands.describe(
        people="분배할 인원수를 입력하세요 (예: 2, 6)",
        amount="분배할 총수익(메소)을 숫자로만 입력하세요"
    )
    async def distribute(self, interaction: discord.Interaction, people: int, amount: int):
        # 인원수 예외 처리
        if people < 2:
            await interaction.response.send_message("인원수는 최소 2명 이상이어야 합니다.", ephemeral=True)
            return

        # N명 분배 공식: 올릴 가격 = 총수익 / (인원수 - 0.03)
        upload_price = math.floor(amount / (people - 0.03))
        
        # 실제 수령액 검증 (수수료 3% 적용)
        final_profit = math.floor(upload_price * 0.97)

        # 디스코드 임베드 생성
        embed = discord.Embed(title=f"💰 보스 수익 1/{people} 분배 계산기", color=0x00ff00)
        
        embed.add_field(name="총 분배할 수익", value=f"{format_meso(amount)}\n({amount:,})", inline=False)
        embed.add_field(name="나머지 파티원들이 올릴 잡템 가격", value=f"**{format_meso(upload_price)}**\n({upload_price:,})", inline=False)
        embed.add_field(name="각자 챙기는 최종 순수익", value=f"{format_meso(final_profit)}\n({final_profit:,})", inline=False)
        
        # 결과 전송
        await interaction.response.send_message(embed=embed)

# 💡 봇이 이 모듈을 인식하게 해주는 필수 함수 (들여쓰기 없이 맨 바깥쪽에 하나만!)
async def setup(bot):
    await bot.add_cog(Distribute(bot))